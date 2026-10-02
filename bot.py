import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, timedelta
import time
import threading
import random
import sqlite3

API_TOKEN = '8758192035:AAE5py1RkU4xxs3Bcvcoi9y8LI9f02aCats'

bot = telebot.TeleBot(API_TOKEN)

# --- ADMIN PERMISSION CONFIGURATION ---
ADMIN_USERNAMES = ['Legend1112220'] 
ADMIN_USER_IDS = []  

def is_admin(user):
    """Check if the user is authorized as Admin"""
    if user.username and user.username in ADMIN_USERNAMES:
        return True
    if user.id in ADMIN_USER_IDS:
        return True
    return False

# Break Duration Limits (in seconds)
BREAK_LIMITS = {
    'Washroom': 15 * 60,
    'Smoke': 10 * 60,
    'Lunch': 30 * 60
}

SHIFT_START_HOUR = 21
SHIFT_START_MINUTE = 0

# --- DATABASE SETUP ---
DB_NAME = "work_monitor.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Table to store permanent employee IDs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            user_id INTEGER PRIMARY KEY,
            emp_id INTEGER UNIQUE,
            emp_name TEXT
        )
    ''')
    
    # Table for daily reports
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            emp_id INTEGER,
            emp_name TEXT,
            date TEXT,
            work_seconds INTEGER DEFAULT 0,
            lunch_count INTEGER DEFAULT 0,
            lunch_seconds INTEGER DEFAULT 0,
            washroom_count INTEGER DEFAULT 0,
            washroom_seconds INTEGER DEFAULT 0,
            smoke_count INTEGER DEFAULT 0,
            smoke_seconds INTEGER DEFAULT 0,
            late_seconds INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Track active states
user_break_data = {}      
user_work_data = {}       
user_off_work = set()     
user_break_stats = {}     
registered_chats = set()

def get_or_create_employee_info(user):
    """Fetch existing permanent ID from DB or create a lifetime fixed ID"""
    user_id = user.id
    user_name = user.first_name + (f" {user.last_name}" if user.last_name else "")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT emp_id FROM employees WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if row:
        emp_id = row[0]
        cursor.execute('UPDATE employees SET emp_name = ? WHERE user_id = ?', (user_name, user_id))
        conn.commit()
    else:
        while True:
            new_emp_id = random.randint(100000000, 999999999)
            cursor.execute('SELECT user_id FROM employees WHERE emp_id = ?', (new_emp_id,))
            if not cursor.fetchone():
                emp_id = new_emp_id
                break
                
        cursor.execute('INSERT INTO employees (user_id, emp_id, emp_name) VALUES (?, ?, ?)', (user_id, emp_id, user_name))
        conn.commit()
        
    conn.close()
    return emp_id, user_name

def get_user_stats(user_id):
    if user_id not in user_break_stats:
        user_break_stats[user_id] = {
            'Lunch': {'count': 0, 'duration': 0},
            'Washroom': {'count': 0, 'duration': 0},
            'Smoke': {'count': 0, 'duration': 0}
        }
    return user_break_stats[user_id]

def save_shift_to_db(user_id, emp_id, emp_name, work_sec, stats, late_sec):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('''
        INSERT INTO daily_reports 
        (user_id, emp_id, emp_name, date, work_seconds, lunch_count, lunch_seconds, washroom_count, washroom_seconds, smoke_count, smoke_seconds, late_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, emp_id, emp_name, today_str, work_sec,
        stats['Lunch']['count'], stats['Lunch']['duration'],
        stats['Washroom']['count'], stats['Washroom']['duration'],
        stats['Smoke']['count'], stats['Smoke']['duration'],
        late_sec
    ))
    conn.commit()
    conn.close()

def get_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = KeyboardButton('Start Work')
    btn2 = KeyboardButton('End Work')
    btn3 = KeyboardButton('Lunch')
    btn4 = KeyboardButton('Washroom')
    btn5 = KeyboardButton('Smoke')
    btn6 = KeyboardButton('Back To Work')
    
    markup.row(btn1, btn2)
    markup.row(btn3, btn4, btn5)
    markup.row(btn6)
    return markup

STATUS_MAP = {
    'Start Work': ('🟢', 'Working', 'Start Work'),
    'End Work': ('🔴', 'Off Work', 'End Work'),
    'Lunch': ('🟡', 'On Lunch Break', 'Lunch'),
    'Washroom': ('🔵', 'In Washroom', 'Washroom'),
    'Smoke': ('🚬', 'Smoking Break', 'Smoke'),
    'Back To Work': ('🟢', 'Working', 'Back To Work'),
}

def format_duration(seconds):
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours} hrs {mins} mins"
    return f"{mins} mins {int(seconds % 60)} secs"

@bot.message_handler(commands=['start', 'panel'])
def send_panel(message):
    registered_chats.add(message.chat.id)
    thread_id = message.message_thread_id if message.is_topic_message else None
    bot.send_message(
        chat_id=message.chat.id,
        text="<b>Work Monitoring Bot</b>\nPunch Panel Enabled",
        parse_mode='HTML',
        reply_markup=get_keyboard(),
        message_thread_id=thread_id
    )

# --- DAILY REPORT COMMAND (ADMIN ONLY) ---
@bot.message_handler(commands=['report', 'allreport'])
def send_all_reports(message):
    thread_id = message.message_thread_id if message.is_topic_message else None
    
    # Permission Check
    if not is_admin(message.from_user):
        bot.send_message(
            chat_id=message.chat.id,
            text="🚫 <b>Access Denied!</b>\nOnly Admin (<b>@Legend1112220</b>) can view report details.",
            parse_mode='HTML',
            message_thread_id=thread_id
        )
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, emp_id, emp_name FROM employees')
    all_employees = cursor.fetchall()
    conn.close()

    if not all_employees:
        bot.send_message(
            chat_id=message.chat.id,
            text="📊 <b>All Employee Shift Report</b>\n\nNo employees registered yet.",
            parse_mode='HTML',
            message_thread_id=thread_id
        )
        return

    report_msg = "📊 <b>All Employee Shift Report</b>\n"
    report_msg += "===========================\n\n"
    now = datetime.now()

    for u_id, emp_id, emp_name in all_employees:
        stats = get_user_stats(u_id)
        
        if u_id in user_off_work:
            status_str = "🔴 Off Work"
        elif u_id in user_break_data:
            b_type = user_break_data[u_id]['type']
            status_str = f"🟡 On {b_type} Break"
        elif u_id in user_work_data:
            status_str = "🟢 Working"
        else:
            status_str = "⚪ Not Started"

        duty_str = "0 hours 0 mins"
        if u_id in user_work_data:
            w_start = user_work_data[u_id]
            total_work = now - w_start
            duty_str = format_duration(int(total_work.total_seconds()))

        report_msg += f"👤 <b>{emp_name}</b> (ID: <code>{emp_id}</code>) | Status: <b>{status_str}</b>\n"
        report_msg += f"⏱️ Duty Time: {duty_str}\n"
        report_msg += f"• Lunch: {stats['Lunch']['count']} time(s) ({format_duration(stats['Lunch']['duration'])})\n"
        report_msg += f"• Washroom: {stats['Washroom']['count']} time(s) ({format_duration(stats['Washroom']['duration'])})\n"
        report_msg += f"• Smoke: {stats['Smoke']['count']} time(s) ({format_duration(stats['Smoke']['duration'])})\n"
        report_msg += "---------------------------\n"

    report_msg += f"\n<b>Generated Time:</b> {now.strftime('%Y-%m-%d %I:%M:%S %p')}"
    bot.send_message(chat_id=message.chat.id, text=report_msg, parse_mode='HTML', message_thread_id=thread_id)

# --- 30-DAY REPORT COMMAND (ADMIN ONLY) ---
@bot.message_handler(commands=['report30'])
def send_30day_report(message):
    thread_id = message.message_thread_id if message.is_topic_message else None
    
    if not is_admin(message.from_user):
        bot.send_message(
            chat_id=message.chat.id,
            text="🚫 <b>Access Denied!</b>\nOnly Admin (<b>@Legend1112220</b>) can access 30-day reports.",
            parse_mode='HTML',
            message_thread_id=thread_id
        )
        return

    args = message.text.split()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    if len(args) > 1:
        target_emp_id = args[1]
        cursor.execute('''
            SELECT emp_name, COUNT(*), SUM(work_seconds), SUM(lunch_count), SUM(lunch_seconds),
                   SUM(washroom_count), SUM(washroom_seconds), SUM(smoke_count), SUM(smoke_seconds), SUM(late_seconds)
            FROM daily_reports
            WHERE emp_id = ? AND date >= ?
        ''', (target_emp_id, thirty_days_ago))
        row = cursor.fetchone()
        conn.close()

        if not row or row[1] == 0:
            bot.send_message(message.chat.id, f"❌ No 30-day records found for Employee ID: <b>{target_emp_id}</b>", parse_mode='HTML', message_thread_id=thread_id)
            return

        emp_name, active_days, total_work, l_cnt, l_sec, w_cnt, w_sec, s_cnt, s_sec, late_sec = row
        offline_days = max(0, 30 - active_days)
        total_time_wasted = (l_sec or 0) + (w_sec or 0) + (s_sec or 0) + (late_sec or 0)

        msg = f"📅 <b>30-Day Detailed Performance Report</b>\n"
        msg += f"=============================\n"
        msg += f"👤 <b>Name:</b> {emp_name}\n"
        msg += f"🆔 <b>Employee ID:</b> {target_emp_id}\n\n"
        msg += f"📊 <b>Attendance Summary (30 Days):</b>\n"
        msg += f"• 🟢 <b>Days Active:</b> {active_days} days\n"
        msg += f"• 🔴 <b>Days Offline/Absent:</b> {offline_days} days\n"
        msg += f"• ⏱️ <b>Total Duty Time:</b> {format_duration(total_work or 0)}\n\n"
        msg += f"⚠️ <b>Time Wasted & Break Breakdown:</b>\n"
        msg += f"• 🔴 <b>Total Time Lost:</b> {format_duration(total_time_wasted)}\n"
        msg += f"  - 🍱 Lunch: {l_cnt or 0} times ({format_duration(l_sec or 0)})\n"
        msg += f"  - 🚻 Washroom: {w_cnt or 0} times ({format_duration(w_sec or 0)})\n"
        msg += f"  - 🚬 Smoke: {s_cnt or 0} times ({format_duration(s_sec or 0)})\n"
        msg += f"  - ⏰ Late Entry Total: {format_duration(late_sec or 0)}\n\n"
        msg += f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %I:%M %p')}"

        bot.send_message(message.chat.id, msg, parse_mode='HTML', message_thread_id=thread_id)
        return

    cursor.execute('''
        SELECT emp_id, emp_name, COUNT(*), SUM(work_seconds), 
               (SUM(lunch_seconds) + SUM(washroom_seconds) + SUM(smoke_seconds) + SUM(late_seconds)) as wasted
        FROM daily_reports
        WHERE date >= ?
        GROUP BY emp_id
    ''', (thirty_days_ago,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        bot.send_message(message.chat.id, "📊 <b>30-Day Summary Report</b>\n\nNo records saved in database for last 30 days.", parse_mode='HTML', message_thread_id=thread_id)
        return

    msg = "📊 <b>30-Day All Employee Overview</b>\n"
    msg += "=============================\n\n"

    for r in rows:
        emp_id, emp_name, active_days, total_work, wasted = r
        offline_days = max(0, 30 - active_days)
        msg += f"👤 <b>{emp_name}</b> (ID: <code>{emp_id}</code>)\n"
        msg += f"• 🟢 Active: {active_days} days | 🔴 Offline: {offline_days} days\n"
        msg += f"• ⏱️ Work Time: {format_duration(total_work or 0)}\n"
        msg += f"• ⚠️ Time Wasted: {format_duration(wasted or 0)}\n"
        msg += "-----------------------------\n"

    msg += "\n💡 <i>Tip: Type <code>/report30 &lt;ID&gt;</code> for specific detailed report.</i>"
    bot.send_message(message.chat.id, msg, parse_mode='HTML', message_thread_id=thread_id)

@bot.message_handler(func=lambda message: message.text in STATUS_MAP.keys())
def handle_status_update(message):
    chat_id = message.chat.id
    user = message.from_user
    user_id = user.id
    action_text = message.text
    registered_chats.add(chat_id)
    thread_id = message.message_thread_id if message.is_topic_message else None

    now = datetime.now()
    current_time_str = now.strftime('%Y-%m-%d %H:%M:%S')
    emp_id, user_name = get_or_create_employee_info(user)
    stats = get_user_stats(user_id)

    if user_id in user_off_work and action_text != 'Start Work':
        bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Access Denied!</b>\n\n<b>Employee:</b> {user_name} (ID: {emp_id})\nYou are currently off work. Click <b>Start Work</b> first.",
            parse_mode='HTML', reply_markup=get_keyboard(), message_thread_id=thread_id
        )
        return

    if user_id in user_break_data and action_text != 'Back To Work':
        active_b = user_break_data[user_id]['type']
        bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ <b>Action Denied!</b>\n\n<b>Employee:</b> {user_name} (ID: {emp_id})\nYou are on <b>{active_b} Break</b>. Click <b>Back To Work</b> first.",
            parse_mode='HTML', reply_markup=get_keyboard(), message_thread_id=thread_id
        )
        return

    # --- BACK TO WORK DUPLICATE CLICK CHECK ---
    if action_text == 'Back To Work':
        if user_id not in user_break_data:
            bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ <b>Already Working!</b>\n\n<b>Employee:</b> {user_name} (ID: {emp_id})\nYou are already working and not on any active break.",
                parse_mode='HTML', reply_markup=get_keyboard(), message_thread_id=thread_id
            )
            return

    emoji, status_en, action = STATUS_MAP[action_text]
    msg = f"<b>Work Monitoring Bot</b>\n{emoji} <b>Employee : {user_name} (ID: {emp_id})</b>\n\n"
    msg += f"<b>Current Status: {status_en}</b>\n<b>Action: {action}</b>\n"

    if action_text == 'Start Work':
        if user_id in user_work_data:
            start_dt = user_work_data[user_id]
            bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ <b>Action Denied!</b>\nAlready working (Started: {start_dt.strftime('%I:%M:%S %p')}). Click <b>End Work</b> first.",
                parse_mode='HTML', reply_markup=get_keyboard(), message_thread_id=thread_id
            )
            return

        if user_id in user_off_work:
            user_off_work.remove(user_id)
            
        user_break_stats[user_id] = {
            'Lunch': {'count': 0, 'duration': 0},
            'Washroom': {'count': 0, 'duration': 0},
            'Smoke': {'count': 0, 'duration': 0}
        }
        user_work_data[user_id] = now
        msg += f"<b>Work Start Time: {now.strftime('%I:%M:%S %p')}</b>\n"

        target_start = now.replace(hour=SHIFT_START_HOUR, minute=SHIFT_START_MINUTE, second=0, microsecond=0)
        late_sec = 0
        if now > target_start:
            late_delta = now - target_start
            late_sec = int(late_delta.total_seconds())
            if late_sec > 0:
                msg += f"⚠ <b>Late Status:</b> Late by {format_duration(late_sec)}\n"

    elif action_text in ['Lunch', 'Washroom', 'Smoke']:
        stats[action_text]['count'] += 1
        duration_mins = 30 if action_text == 'Lunch' else (15 if action_text == 'Washroom' else 10)
        user_break_data[user_id] = {
            'type': action_text,
            'start_time': time.time(),
            'start_dt': now,
            'chat_id': chat_id,
            'thread_id': thread_id,
            'user_mention': f"@{user.username}" if user.username else user_name
        }
        msg += f"<b>Allowed Break Time: {duration_mins} minutes</b>\n"
        msg += f"📊 <b>{action_text} Count Today: {stats[action_text]['count']} time(s)</b>\n"

    elif action_text == 'Back To Work':
        b_info = user_break_data[user_id]
        b_type = b_info['type']
        start_dt = b_info['start_dt']
        diff_seconds = int((now - start_dt).total_seconds())
        stats[b_type]['duration'] += diff_seconds
        
        allowed_secs = BREAK_LIMITS[b_type]
        late_secs = max(0, diff_seconds - allowed_secs)
        
        msg += f"<b>Break Taken:</b> {b_type}\n<b>Duration Spent:</b> {format_duration(diff_seconds)}\n"
        if late_secs > 0:
            msg += f"⚠️ <b>Late Status:</b> Exceeded limit by {format_duration(late_secs)}\n"
        else:
            msg += f"✅ <b>Status:</b> Returned within time limit\n"
        del user_break_data[user_id]

    elif action_text == 'End Work':
        user_off_work.add(user_id)
        if user_id in user_work_data:
            w_start = user_work_data[user_id]
            total_work_sec = int((now - w_start).total_seconds())
            
            target_start = w_start.replace(hour=SHIFT_START_HOUR, minute=SHIFT_START_MINUTE, second=0, microsecond=0)
            late_sec = max(0, int((w_start - target_start).total_seconds())) if w_start > target_start else 0

            save_shift_to_db(user_id, emp_id, user_name, total_work_sec, stats, late_sec)

            msg += f"<b>Total Duty Time:</b> {format_duration(total_work_sec)}\n"
            msg += f"📊 <b>Shift Summary (Saved To DB):</b>\n"
            for b_name in ['Lunch', 'Washroom', 'Smoke']:
                b_count = stats[b_name]['count']
                b_dur = stats[b_name]['duration']
                msg += f"• <b>{b_name}:</b> {b_count} time(s) | Spent: {format_duration(b_dur)}\n"
            
            del user_work_data[user_id]
            
        if user_id in user_break_data:
            del user_break_data[user_id]

    msg += f"\n<b>Time:</b>\n<b>{current_time_str}</b>"
    bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML', reply_markup=get_keyboard(), message_thread_id=thread_id)

def background_scheduler():
    start_reminder_sent = False
    while True:
        now = datetime.now()
        current_time_str = now.strftime('%H:%M')
        current_date_str = now.strftime('%Y-%m-%d %H:%M')

        if current_time_str == "20:45":
            if not start_reminder_sent:
                start_reminder_sent = True
                msg = f"<b>Work Monitoring Bot</b>\n🏁 <b>Start Work Reminder</b>\n\nWork starting in 15 mins!\n\n<b>Time:</b>\n{current_date_str}"
                for c_id in list(registered_chats):
                    try:
                        bot.send_message(c_id, msg, parse_mode='HTML')
                    except Exception:
                        pass
        else:
            start_reminder_sent = False

        now_ts = time.time()
        for u_id, break_info in list(user_break_data.items()):
            b_type = break_info['type']
            limit = BREAK_LIMITS.get(b_type, 900)
            elapsed = now_ts - break_info['start_time']

            if elapsed > limit:
                elapsed_mins = int(elapsed // 60)
                user_ref = break_info['user_mention']
                c_id = break_info['chat_id']
                t_id = break_info['thread_id']

                timeout_msg = (
                    f"⏰ <b>Break Timeout Warning</b>\n\n"
                    f"<b>Employee:</b> {user_ref}\n"
                    f"<b>Break Type:</b> {b_type} Break\n"
                    f"<b>Duration:</b> {elapsed_mins} minutes\n\n"
                    f"<i>Break limit exceeded! Return to work immediately!</i>\n\n"
                    f"<b>Time:</b>\n{current_date_str}"
                )
                try:
                    bot.send_message(c_id, timeout_msg, parse_mode='HTML', message_thread_id=t_id)
                except Exception:
                    pass
                del user_break_data[u_id]

        time.sleep(10)

threading.Thread(target=background_scheduler, daemon=True).start()

print("Work Monitoring Bot is running...")

while True:
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=30)
    except Exception as e:
        time.sleep(5)