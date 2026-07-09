import discord
from discord.ext import commands
from google import genai
from google.genai import types
import json
import os
import random
import asyncio
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# --- 1. NẠP VÀ PHÂN TẢI API KEY ---
api_keys_str = os.getenv('GEMINI_API_KEYS', '')
GEMINI_API_KEYS = [k.strip() for k in api_keys_str.split(',') if k.strip()]

if not GEMINI_API_KEYS:
    print("❌ LỖI: Chưa cấu hình GEMINI_API_KEYS trong file .env sếp ơi!")
    exit()

# Khởi tạo danh sách Client AI
ai_clients = [genai.Client(api_key=key) for key in GEMINI_API_KEYS]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CONFIG_FILE = 'config.json'
BOT_PERSONALITY = (
    "Bạn là Kizuna AI, một thành viên vui tính, nhiệt tình trong server Discord này. "
    "Nhiệm vụ của bạn là đọc lịch sử chat, đọc file văn bản, nhìn hình ảnh và nghe âm thanh để hiểu ngữ cảnh, "
    "sau đó trả lời câu hỏi, phân tích code, dịch thuật hoặc hùa theo cuộc trò chuyện. "
    "Luôn xưng hô là 'mình' - 'bạn' hoặc 'em' - 'sếp'. "
    "Hãy nhớ các chi tiết trong lịch sử chat để duy trì cuộc trò chuyện liền mạch."
)

# --- QUẢN LÝ WHITELIST (KÊNH CHO PHÉP) ---
def load_allowed_channels():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f).get('allowed_channels', [])
        except Exception:
            return []
    return []

def save_allowed_channels(channels_list):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({'allowed_channels': channels_list}, f)

# --- HÀM CẮT TIN NHẮN THÔNG MINH ---
def split_message(text, limit=1900):
    """Cắt tin nhắn dài nhưng không làm đứt đoạn giữa chừng một cách vô lý"""
    if len(text) <= limit:
        return [text]
    
    chunks = []
    while len(text) > limit:
        split_at = text.rfind('\n', 0, limit)
        if split_at == -1: # Không tìm thấy dấu xuống dòng, đành cắt cứng
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks

@bot.event
async def on_ready():
    print('='*40)
    print(f'🤖 Bot {bot.user} ĐÃ SẴN SÀNG!')
    print(f'🔑 Số lượng API Key đang chạy song song: {len(ai_clients)}')
    print(f'🛡️ Đang bảo vệ {len(load_allowed_channels())} kênh.')
    print('='*40)

# --- CÁC LỆNH ADMIN ---
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    allowed = load_allowed_channels()
    if ctx.channel.id not in allowed:
        allowed.append(ctx.channel.id)
        save_allowed_channels(allowed)
        await ctx.send(f"✅ **Đã duyệt!** Kênh <#{ctx.channel.id}> đã được đưa vào hệ thống hoạt động.")
    else:
        await ctx.send(f"⚠️ Kênh này đã được setup từ trước rồi sếp ơi!")

@bot.command()
@commands.has_permissions(administrator=True)
async def removesetup(ctx):
    allowed = load_allowed_channels()
    if ctx.channel.id in allowed:
        allowed.remove(ctx.channel.id)
        save_allowed_channels(allowed)
        await ctx.send(f"❌ **Đã gỡ bỏ!** Bot sẽ ngừng hoạt động tại kênh <#{ctx.channel.id}>.")
    else:
        await ctx.send(f"❓ Kênh này chưa từng được setup sếp ạ.")

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author == bot.user or message.channel.id not in load_allowed_channels():
        return  

    # Kích hoạt khi được Tag (Mention)
    if bot.user in message.mentions:
        async with message.channel.typing():
            try:
                # 1. XỬ LÝ FILE & ẢNH (GIỮ NGUYÊN NHƯNG GỌN HƠN)
                attached_parts = []
                file_text_content = ""
                
                # Các định dạng file text được hỗ trợ
                text_extensions = ('.txt', '.py', '.json', '.md', '.csv', '.html', '.js', '.mcfunction', '.c', '.cpp', '.java')

                for attachment in message.attachments:
                    if attachment.content_type:
                        if attachment.content_type.startswith(('image/', 'audio/', 'video/')):
                            file_bytes = await attachment.read()
                            attached_parts.append(types.Part.from_bytes(
                                data=file_bytes,
                                mime_type=attachment.content_type
                            ))
                        elif attachment.content_type.startswith('text/') or attachment.filename.endswith(text_extensions):
                            try:
                                file_bytes = await attachment.read()
                                file_text_content += f"\n\n--- FILE: {attachment.filename} ---\n{file_bytes.decode('utf-8')}\n--- END FILE ---\n"
                            except Exception as e:
                                print(f"Lỗi đọc file text {attachment.filename}: {e}")

                # 2. XÂY DỰNG TRÍ NHỚ TỪ LỊCH SỬ CHAT (Tăng lên 50 câu để nhớ lâu hơn)
                messages = [msg async for msg in message.channel.history(limit=90)]
                messages.reverse() # Xếp theo thứ tự thời gian chuẩn

                chat_context = ""
                for msg in messages:
                    # Bỏ qua các lệnh bot ngắn để đỡ tốn token
                    if msg.content and not msg.content.startswith('!'):
                        sender = "Kizuna AI" if msg.author == bot.user else msg.author.display_name
                        clean_content = msg.content.replace(f'<@{bot.user.id}>', '').strip()
                        if clean_content:
                            chat_context += f"{sender}: {clean_content}\n"
                
                # 3. NHẬN DIỆN NGỮ CẢNH ĐƯỢC REPLY TRỰC TIẾP
                replied_context = ""
                if message.reference and message.reference.message_id:
                    try:
                        replied_msg = await message.channel.fetch_message(message.reference.message_id)
                        replied_sender = "Kizuna AI" if replied_msg.author == bot.user else replied_msg.author.display_name
                        clean_replied = replied_msg.content.replace(f'<@{bot.user.id}>', '').strip()
                        if clean_replied:
                            replied_context = (
                                f"\n\n[🔥 NGỮ CẢNH TRỌNG TÂM: Người dùng đang Reply tin nhắn sau của {replied_sender}]:\n"
                                f"\"{clean_replied}\"\n-> Hãy tập trung trả lời dựa trên tin nhắn này!\n"
                            )
                    except:
                        pass

                # 4. TỔNG HỢP PROMPT
                final_prompt = (
                    f"Dưới đây là trí nhớ ngắn hạn về cuộc trò chuyện hiện tại:\n\n{chat_context}\n"
                    f"{replied_context}\n"
                    f"Người dùng vừa gửi yêu cầu mới. Hãy phản hồi thật tự nhiên nhé."
                )

                if file_text_content:
                    final_prompt += file_text_content

                contents_list = [final_prompt] + attached_parts

                # 5. CƠ CHẾ ĐA KEY & ĐA LUỒNG (ASYNC LOAD BALANCING)
                # Xáo trộn danh sách key để chia đều tải (tránh tình trạng dồn hết vào 1 key)
                available_clients = random.sample(ai_clients, len(ai_clients))
                ai_reply = None
                
                for client in available_clients:
                    try:
                        # QUAN TRỌNG: Sử dụng client.aio thay vì client thường để không bị nghẽn (Block) đa kênh
                        response = await client.aio.models.generate_content(
                            model='gemini-3.5-flash', # Đổi sang bản model nhanh nhất hiện tại
                            contents=contents_list,
                            config=types.GenerateContentConfig(
                                system_instruction=BOT_PERSONALITY,
                            )
                        )
                        ai_reply = response.text
                        break # Gọi thành công thì thoát vòng lặp thử Key
                    except Exception as api_error:
                        print(f"⚠️ Một Key vừa bị nghẽn/hết token ({api_error}). Đang thử Key dự phòng...")

                if not ai_reply:
                    await message.reply("Sếp ơi, toàn bộ API Key đã sập mạng hoặc hết hạn mức (Quota). Xin hãy kiểm tra lại! 😭")
                    return

                # 6. TRẢ LỜI VỚI HÀM CẮT THÔNG MINH
                response_chunks = split_message(ai_reply)
                await message.reply(response_chunks[0])
                
                for chunk in response_chunks[1:]:
                    await asyncio.sleep(0.5) # Nghỉ nửa giây tránh bị Discord rate limit
                    await message.channel.send(chunk)
                
            except Exception as e:
                print(f"Lỗi toàn cục: {e}")
                await message.reply("Ui sếp ơi em bị lỗi kĩ thuật (lag hệ thống) rồi, check Terminal cứu em với! 😭")

bot.run(DISCORD_TOKEN)