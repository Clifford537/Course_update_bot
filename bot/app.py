from datetime import datetime
import hashlib
import pymysql
import telegram
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from telegram import Bot
from pymysql import IntegrityError
from apscheduler.schedulers.background import BackgroundScheduler
import logging

app = Flask(__name__)

# MySQL configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_PORT'] = 3302
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'cliff'
app.config['MYSQL_DB'] = 'telegrambot_v4'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# Initialize PyMySQL
mysql = pymysql.connect(
    host=app.config['MYSQL_HOST'],
    port=app.config['MYSQL_PORT'],
    user=app.config['MYSQL_USER'],
    password=app.config['MYSQL_PASSWORD'],
    db=app.config['MYSQL_DB'],
    cursorclass=pymysql.cursors.DictCursor
)

# Set up Flask-MySQL connection
app.config['MYSQL'] = mysql



TELEGRAM_BOT_TOKEN = '6801294138:AAHuZ6EY7lgOKvVCiFK6fT_mJBW6LOXioHs'

# Create a bot instance (initialize once, not within send_message)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

# Change this line in your MySQL configuration
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# Secret key for session management
app.secret_key = 'your_secret_key'  # Change this to a secure key


@app.errorhandler(404)
def page_not_found(e):
    return render_template('errorpage.html', error_message='Page not found'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('errorpage.html', error_message='Internal server error'), 500


@app.route('/')
def index():
    return render_template('start.html')


@app.route('/signin', methods=['GET', 'POST'], endpoint='signin')
def signin():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            # Get the cursor from the connection
            with mysql.cursor() as cur:
                cur.execute("SELECT * FROM lecturers WHERE lecturer_email = %s", (email,))
                lecturer = cur.fetchone()

                if lecturer and hashlib.sha256(password.encode('utf-8')).hexdigest() == lecturer['lecturer_password']:
                    session['email'] = email
                    flash('Login successful!', 'success')
                    return redirect(url_for('main_page'))
                else:
                    flash('Incorrect email or password. Please try again.', 'error')
                    return render_template('signin.html')

        except Exception as e:
            print(f"Error in signin: {e}")
            flash('An error occurred. Please try again.', 'error')
            return render_template('signin.html')

    return render_template('signin.html')



@app.route('/signup', methods=['GET', 'POST'], endpoint='signup')
def signup():
    if request.method == 'POST':
        try:
            lecturer_name = request.form['lecturer_name']
            email = request.form['lecturer_email']
            password = request.form['password']

            # Hash the password before storing it in the database
            hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()

            class_name = request.form['class']
            code = request.form['code']

            # Get the selected groups from the checkboxes
            selected_groups = request.form.getlist('selected_groups')

            # Convert selected groups to a comma-separated string
            group_names = ','.join(selected_groups)

            with mysql.cursor() as cur:
                cur.execute("INSERT INTO lecturers (lecturer_name, lecturer_email, lecturer_password, lecturer_class, lecturer_code, group_name) VALUES (%s, %s, %s, %s, %s, %s)",
                            (lecturer_name, email, hashed_password, class_name, code, group_names))
                mysql.commit()

            session['email'] = email  # Optional: Automatically log in the user after signup
            flash('Registration successful! Your information has been submitted.', 'success')
            return redirect(url_for('signup'))  # Redirect back to the signup page to display the flash message
        except IntegrityError:
            flash('Email already exists. Please use a different email address.', 'error')

    # Fetch the groups from the database
    with mysql.cursor() as cur:
        cur.execute("SELECT name FROM telegram_groups")
        groups_data = cur.fetchall()

    # Extract group names from the list of dictionaries
    groups = [group['name'] for group in groups_data]

    # Pass the group names to the template
    return render_template('signup.htm', groups=groups)

@app.route('/main_page', methods=['GET'])
def main_page():
    if 'email' in session:
        return render_template('main_page.htm', send_message_url=url_for('send_message'))
    else:
        return redirect(url_for('signin'))
    
    
@app.route('/get_registered_groups', methods=['GET'])
def get_registered_groups():
    try:
        lecturer_email = session.get('email')  # Assuming you store the lecturer's email in the session
        if not lecturer_email:
            return jsonify({'success': False, 'error': 'User not logged in.'}), 401

        # Fetch registered groups for the lecturer from the database
        with mysql.cursor() as cur:
            cur.execute("SELECT group_name FROM lecturers WHERE lecturer_email = %s", (lecturer_email,))
            result = cur.fetchone()
            if result:
                registered_groups = result['group_name'].split(',')
                print("Registered Groups:", registered_groups)  # Print the group names
            else:
                registered_groups = []

        return jsonify({'success': True, 'registeredGroups': registered_groups})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})




@app.route('/send_message', methods=['POST'])
async def send_message():
    message_text = request.form.get('message')
    sender_email = session.get('email')
    sender_name = session.get('lecturer_name')

    try:
        # Save the message to the database
        with mysql.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (name, sender_name, message_text, class, timestamp, code) VALUES (%s, %s, %s, %s, %s, %s)",
                (sender_name, sender_email, message_text, '303', datetime.now(), 'code')
            )
            mysql.commit()

        # Log success
        logging.info('Message saved to the database successfully.')

    except Exception as save_error:
        # Log error
        logging.error(f"Error saving message to the database: {save_error}")

        print(f"Error saving message to the database: {save_error}")
        flash('An error occurred while saving the message. Please try again.', 'error')

        # Return an error response for database saving failure
        return jsonify({'success': False})


    try:
        # Attempt to send the message to the Telegram bot and channels
        bot = Bot(token='6801294138:AAHuZ6EY7lgOKvVCiFK6fT_mJBW6LOXioHs')

        sender_name = session.get('lecturer_name', 'Unknown User')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"{sender_email} sent a message at\n {timestamp}:\n\n{message_text}"
        await bot.send_message(chat_id="5706754147", text=full_message)
        await bot.send_message(chat_id="@botv1class", text=full_message)


        # Log success
        logging.info('Message sent successfully.')

        flash('Message sent successfully!', 'success')

        # Return a success response for message sending success
        return jsonify({'success': True})

    except Exception as send_error:
        # Log error
        logging.error(f"Error sending message: {send_error}")

        print(f"Success! Message saved but an error occurred while sending. Please try again.")
        flash('Message sent successfully, but there was an issue with sending. Please try again.', 'success')

        # Return a success response despite message sending failure
        return jsonify({'success': True})


@app.route('/change_password', methods=['GET', 'POST'], endpoint='change_password')
def change_password():
    if request.method == 'POST':
        email = session.get('email')  # Assuming the user is logged in
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # Verify the old password before changing
        cur = mysql.cursor()
        cur.execute("SELECT password FROM lecturers WHERE email = %s", (email,))
        result = cur.fetchone()
        cur.close()

        if result and hashlib.sha256(old_password.encode('utf-8')).hexdigest() == result['password']:
            # Old password is correct, proceed with changing the password
            if new_password == confirm_password:
                # Hash the new password before updating it in the database
                hashed_password = hashlib.sha256(new_password.encode('utf-8')).hexdigest()

                cur = mysql.cursor()
                cur.execute("UPDATE lecturers SET password = %s WHERE email = %s", (hashed_password, email))
                mysql.commit()
                cur.close()

                flash('Password changed successfully!', 'success')
                return redirect(url_for('change_password'))
            else:
                flash('New password and confirm password do not match. Please try again.', 'error')
        else:
            flash('Old password is incorrect. Please try again.', 'error')

    return render_template('change_password.html')


@app.route('/forget_password', methods=['GET', 'POST'])
def forget_password():
    if request.method == 'POST':
        email = request.form['email']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password == confirm_password:
            # Hash the new password before updating it in the database
            hashed_password = hashlib.sha256(new_password.encode('utf-8')).hexdigest()

            try:
                # Create a cursor and execute the SQL query
                with mysql.cursor() as cur:
                    # Check if the email exists in the database
                    cur.execute("SELECT * FROM lecturers WHERE lecturer_email = %s", (email,))
                    lecturer = cur.fetchone()
                    if lecturer:
                        # Update the password for the corresponding email
                        cur.execute("UPDATE lecturers SET lecturer_password = %s WHERE lecturer_email = %s", (hashed_password, email))
                        # Commit the changes to the database
                        mysql.commit()
                        flash('Password changed successfully!', 'success')
                        return redirect(url_for('index'))
                    else:
                        flash('Email address not found. Please enter a valid email address.', 'error')
            except pymysql.Error as e:
                # Log or print the error, and display a flash message
                print(f"Error updating password: {e}")
                flash('An error occurred. Please try again.', 'error')
        else:
            flash('New password and confirm password do not match. Please try again.', 'error')

    return render_template('forget_password.html')

@app.route('/logout')
def logout():
    if 'email' in session:
        session.pop('email', None)
        return render_template('logout.html')
    else:
        return redirect(url_for('signin'))


if __name__ == '__main__':
    app.run(debug=True)
