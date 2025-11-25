import json
import boto3
import urllib3
from decimal import Decimal

# --- CONFIGURATION ---
DYNAMODB_TABLE_NAME = 'PriceTrackingConfig'
# *** แก้ไข: นำ SNS ARN ของคุณมาใส่แทนที่ ***
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:123456789012:PriceAlertTopic' 

# SETUP SERVICES
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)
http = urllib3.PoolManager()

def get_real_crypto_price(product_name):
    """
    ดึงราคา Real-time จาก CoinGecko API
    รองรับ: Bitcoin, Ethereum, Dogecoin, Solana และอื่นๆ
    """
    # แปลงชื่อให้เป็นตัวพิมพ์เล็กเพื่อใช้เป็น ID (เช่น Ethereum -> ethereum)
    coin_id = product_name.lower()
    
    # URL API สำหรับดึงราคา
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    
    try:
        # ยิง Request ไปที่ API
        response = http.request('GET', url)
        
        if response.status == 200:
            data = json.loads(response.data.decode('utf-8'))
            # เช็คว่ามีข้อมูลของเหรียญนั้นจริงๆ ไหม
            if coin_id in data:
                price = data[coin_id]['usd']
                return float(price)
            else:
                print(f"API Warning: ไม่พบข้อมูลราคาของ '{coin_id}'")
                return None
        else:
            print(f"API Error: Status {response.status}")
            return None
            
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

def lambda_handler(event, context):
    print("--- เริ่มตรวจสอบราคา Crypto (Real API / KMS Secured) ---")
    
    try:
        response = table.scan()
        items = response.get('Items', [])
    except Exception as e:
        print(f"Database Error: {e}")
        return {'statusCode': 500, 'body': "Database Error"}

    for item in items:
        product_name = item.get('productName')
        target_price = float(item.get('targetPrice', 0))
        
        # 1. ดึงราคาจริง
        current_price = get_real_crypto_price(product_name)
        
        if current_price is None: continue
            
        print(f"เหรียญ: {product_name} | ราคาตลาด: ${current_price:,.4f} | เป้าหมาย: ${target_price:,.4f}")

        # 2. เช็คเงื่อนไขแจ้งเตือน (ราคาต่ำกว่าเป้าหมาย)
        if current_price < target_price:
            msg = (f"CRYPTO ALERT! {product_name} ราคาแตะเป้าหมายแล้ว!\n"
                   f"ราคาปัจจุบัน: ${current_price:,.4f} USD\n"
                   f"ราคาเป้าหมาย: ${target_price:,.4f} USD")
            
            try:
                sns.publish(TopicArn=SNS_TOPIC_ARN, Message=msg, Subject=f"Price Alert: {product_name}")
                print(f">> ส่งอีเมลแจ้งเตือน {product_name} สำเร็จ")
            except Exception as e:
                print(f"SNS Failed: {e}")

        # 3. อัปเดตราคาลง DB
        try:
            table.update_item(
                Key={'productName': product_name},
                UpdateExpression="set lastCheckedPrice = :p",
                ExpressionAttributeValues={':p': Decimal(str(current_price))}
            )
        except Exception as e:
            print(f"Update DB Failed: {e}")

    return {'statusCode': 200, 'body': "Check Complete"}