import os
from dotenv import load_dotenv
from google import genai

# Tải API Key từ file .env của bạn
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = genai.Client(api_key=GEMINI_API_KEY)

print("Đang quét danh sách các mô hình khả dụng cho API Key của bạn...")
print("-" * 50)

# In ra toàn bộ tên mô hình hỗ trợ tính năng tạo văn bản (generateContent)
for model_info in client.models.list():
    if "generateContent" in model_info.supported_actions:
        print(f"Tên chuẩn: '{model_info.name}'")