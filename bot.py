import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

BOT_TOKEN = os.environ["BOT_TOKEN"]
# The bot itself still needs its own API_ID/API_HASH to run as a bot
BOT_API_ID = int(os.environ["BOT_API_ID"])
BOT_API_HASH = os.environ["BOT_API_HASH"]

bot = TelegramClient("bot", BOT_API_ID, BOT_API_HASH).start(bot_token=BOT_TOKEN)

user_clients = {}  # uid -> TelegramClient
user_data = {}     # uid -> dict of temp data
user_state = {}    # uid -> current step

@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    await event.respond(
        "👋 Send /generate to create your Telethon string session.\n\n"
        "⚠️ Never share your string session with anyone — "
        "it gives full access to your Telegram account."
    )

@bot.on(events.NewMessage(pattern="/cancel"))
async def cancel(event):
    await cleanup(event.sender_id)
    await event.respond("❌ Cancelled. Send /generate to start again.")

@bot.on(events.NewMessage(pattern="/generate"))
async def generate(event):
    uid = event.sender_id
    await cleanup(uid)  # clear any previous incomplete session
    user_data[uid] = {}
    user_state[uid] = "awaiting_api_id"
    await event.respond(
        "🔢 Send your **API_ID** (get it from https://my.telegram.org → API Development Tools):"
    )

@bot.on(events.NewMessage())
async def handle_input(event):
    uid = event.sender_id
    if uid not in user_state:
        return

    state = user_state[uid]
    text = event.raw_text.strip()

    try:
        if state == "awaiting_api_id":
            if not text.isdigit():
                await event.respond("⚠️ API_ID must be a number. Try again:")
                return
            user_data[uid]["api_id"] = int(text)
            user_state[uid] = "awaiting_api_hash"
            await event.respond("🔑 Now send your **API_HASH**:")

        elif state == "awaiting_api_hash":
            user_data[uid]["api_hash"] = text
            client = TelegramClient(StringSession(), user_data[uid]["api_id"], user_data[uid]["api_hash"])
            await client.connect()
            user_clients[uid] = client
            user_state[uid] = "awaiting_phone"
            await event.respond("📱 Send your phone number in international format (e.g. +11234567890):")

        elif state == "awaiting_phone":
            client = user_clients[uid]
            phone = text
            result = await client.send_code_request(phone)
            user_data[uid]["phone"] = phone
            user_data[uid]["phone_code_hash"] = result.phone_code_hash
            user_state[uid] = "awaiting_code"
            await event.respond(
                "🔑 Enter the OTP you received, **with a space between each digit** "
                "(e.g. `1 2 3 4 5`) — this stops Telegram from auto-expiring the code:"
            )

        elif state == "awaiting_code":
            client = user_clients[uid]
            code = text.replace(" ", "")
            try:
                await client.sign_in(
                    phone=user_data[uid]["phone"],
                    code=code,
                    phone_code_hash=user_data[uid]["phone_code_hash"],
                )
            except SessionPasswordNeededError:
                user_state[uid] = "awaiting_password"
                await event.respond("🔒 Two-step verification is enabled. Send your password:")
                return

            session_str = client.session.save()
            await event.respond(f"✅ Your string session:\n\n`{session_str}`")
            await cleanup(uid)

        elif state == "awaiting_password":
            client = user_clients[uid]
            await client.sign_in(password=text)
            session_str = client.session.save()
            await event.respond(f"✅ Your string session:\n\n`{session_str}`")
            await cleanup(uid)

    except PhoneCodeInvalidError:
        await event.respond("❌ Invalid code. Send /generate to try again.")
        await cleanup(uid)
    except PhoneCodeExpiredError:
        await event.respond("❌ Code expired. Send /generate to try again.")
        await cleanup(uid)
    except Exception as e:
        await event.respond(f"❌ Error: {e}\nSend /generate to try again.")
        await cleanup(uid)

async def cleanup(uid):
    client = user_clients.pop(uid, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    user_data.pop(uid, None)
    user_state.pop(uid, None)

print("Bot running...")
bot.run_until_disconnected()
