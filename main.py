from datetime import date
from flask import Flask, render_template, request, redirect, url_for, session, abort
from flask_mysqldb import MySQL
import pypyodbc as odbc  # pip install pypyodbc
import re

app = Flask(__name__)

app.secret_key = 'your secret key'

server = 'empirefishing.database.windows.net'
database = 'EmpireFishingCSCI-4485'
dbusername = 'empirefishing'
dbpassword = '@Stockton'
connection_string = (
        'Driver={ODBC Driver 18 for SQL Server};Server=' + server + ',1433;Database=' + database + ';Uid=' + dbusername + ';Pwd=' + dbpassword + ';Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;')
conn = odbc.connect(connection_string)

mysql = MySQL(app)


@app.route('/')
def home():
    return render_template("index.html")


@app.errorhandler(404)
def error404():
    return render_template("404.html")


@app.route('/bait-editor')
def bait_editor():
    return render_template("bait-editor.html")

@app.route('/admin')
def admin():
    return render_template("admin.html")

@app.route('/temp-bait-editor', methods=['GET', 'POST'])
def temp_bait_editor():
    if 'loggedin' not in session.keys():
        return redirect(url_for('login'))

    username = session['username']
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM userdata WHERE username = ?', (username,))
    account = cursor.fetchone()

    if not account['admin']:
        abort(403)

    cursor.execute('SELECT * FROM bait')
    baits = cursor.fetchall()

    return render_template("temp-bait-editor.html", baits=baits)


@app.route('/bait')
def live_bait():
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bait')
    baits = cursor.fetchall()

    return render_template("bait.html", baits=baits)


@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''

    # check if username and password were received
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:

        username = request.form['username']
        password = request.form['password']

        # Check if account exists using MySQL - Grabs from userdata table on Azure SQL Server
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM userdata WHERE username = ? AND password = ?', (username, password))

        # Fetch one record and return result
        account = cursor.fetchone()

        if account:
            # Create session data, we can access this data in other routes
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']

            # Redirect to profile
            return redirect(url_for('profile'))
        else:
            # Account doesn't exist or username/password incorrect
            msg = 'Incorrect username/password!'
            # Show the login form with message (if any)
    return render_template('login.html', msg=msg)


@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('username', None)
    return redirect(url_for('home'))


@app.route('/profile')
def profile():
    # if user is not logged in, return to login screen
    if 'loggedin' not in session.keys():
        return redirect(url_for('login'))

    username = session['username']
    email = "(placeholder)"
    phone = "(placeholder)"

    return render_template("profile.html", username=username, email=email, phone=phone)


@app.route('/register', methods=['GET', 'POST'])
def register():
    # Output message if something goes wrong...
    msg = ''
    # Check if "username", "password" and "email" POST requests exist (user submitted form)
    if (request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'email' in
            request.form):

        # Create variables for easy access
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        phone = request.form['phone']
        if request.form['consent']:  # 1 yes 0 no
            consent = 1
        else:
            consent = 0

        # Check if account exists using MySQL
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM userdata WHERE username = ?', (username,))
        account = cursor.fetchone()

        # If account exists show error and validation checks
        if account:
            msg = 'Account already exists!'
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            msg = 'Invalid email address!'
        elif not re.match(r'[A-Za-z0-9]+', username):
            msg = 'Username must contain only characters and numbers!'
        elif len(password) < 3:
            msg = 'Password too short!'
        elif len(phone) < 12:
            msg = 'Invalid Phone Number!'
        elif not username or not password or not email:
            msg = 'Please fill out the form!'
        else:
            # Account doesn't exist and the form data is valid, now insert new account into accounts table
            cursor.execute('INSERT INTO userdata VALUES ( ?, ?, ?, ?, ?, ?, ?, ?)',
                           (username, password, email, consent, phone, 0, id, date.today()))
            # today sets the account creation date, zero is for not admin
            conn.commit()
            msg = 'You have successfully registered!'

    elif request.method == 'POST':
        # Form is empty... (no POST data)
        msg = 'Please fill out the form!'
    # Show registration form with message (if any)
    return render_template('register.html', msg=msg)


if __name__ == '__main__':
    app.run()