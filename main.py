from flask import Flask, render_template, request, redirect, url_for, session, abort
from flask_mysqldb import MySQL
import pypyodbc as odbc
import requests
import random
import time
import math
import re
import os
import argon2
from datetime import datetime

app = Flask(__name__)

app.secret_key = 'your secret key'

# SQL Azure Server
server = ''
database = ''
dbusername = ''
dbpassword = ''
connection_string = (
        'Driver={ODBC Driver 18 for SQL Server};Server=' + server + ',1433;Database=' + database + ';Uid=' + dbusername + ';Pwd=' + dbpassword + ';Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;')
conn = odbc.connect(connection_string)

mysql = MySQL(app)

hasher = argon2.PasswordHasher()

# Mailgun API
api_key = ""
domain = ""
sender = "Empire Fishing and Tackle <>"

def send_email(recipient, subject, message):
    # (because we are using for free I have to manually approve emails)
    """
    :param recipient: All array of emails who are going to be receiving message
    :type recipient: string array
    :param subject: Subject of email
    :type subject: string
    :param message: Message to be sent to users
    :type message: string
    :return:
    """
    return requests.post(
        f"https://api.mailgun.net/v3/{domain}/messages",
        auth=("api", api_key),
        data={"from": sender,
              "to": recipient,
              "subject": subject,
              "text": message})


def send_receipt(username):
    receipt_text = ""

    cursor = conn.cursor()
    cursor.execute('SELECT products.product_name, products.price, cart.quantity FROM cart INNER JOIN products ON cart.product_id = products.product_id WHERE username = ?', (username,))
    cart_items = cursor.fetchall()

    cursor.execute('SELECT email FROM userdata WHERE username = ?', (username,))
    email = cursor.fetchone()[0]

    total = 0

    for item in cart_items:
        receipt_text += "\n(%d * $%.2f) %s" % (item[2], item[1], item[0])
        total += item[2]*item[1]

    receipt_text += "\nTotal: $%.2f" % total
    receipt_text += "\n\nThank you for shopping at Empire Fishing!"

    send_email([email], "Your receipt", receipt_text)


def require_login_status(must_be_logged_out=False, must_be_admin=False, destination='profile'):
    # if user needs to be logged in but isn't, return to login page
    if 'loggedin' not in session.keys() and not must_be_logged_out:
        return redirect(url_for('login') + '?destination=' + destination)

    # if user is logged in but shouldn't be, return to profile page
    if 'loggedin' in session.keys() and must_be_logged_out:
        return redirect('/' + destination)

    # if user is logged in but isn't an admin, return 403 for admin-only pages
    if must_be_admin and not session['admin']:
        abort(403)


def average_product_rating(cursor, product_id):
    cursor.execute('SELECT rating FROM ratings WHERE product = ?', (product_id,))
    l = [i[0] for i in cursor.fetchall()]
    return sum(l)/len(l) if len(l) != 0 else 0


@app.route('/')
def home():
    return render_template("index.html", session=session)


@app.route('/lineSpooling')
def lineSpooling():
    return render_template("lineSpooling.html", session=session)


@app.errorhandler(404)
def error404(error):
    return render_template("404.html", session=session)


@app.route('/admin')
def admin():
    login_status = require_login_status(must_be_admin=True, destination='admin')
    if login_status is not None:
        return login_status

    return render_template("admin.html", session=session)


@app.route('/send_promotional_emails', methods=['GET', 'POST'])
def send_promo():
    login_status = require_login_status(must_be_admin=True, destination='admin')
    if login_status is not None:
        return login_status

    msg = ''

    if request.method == 'POST':
        # get user input from form
        email_subject = request.form['subject']
        email_message = request.form['message']

        # get all users with consent from sql database
        cursor = conn.cursor()
        cursor.execute('SELECT email FROM userdata WHERE email_consent = 1')
        emails = cursor.fetchall()

        # sending emails looping for each user on list
        for email in emails:
            send_email(email, email_subject, email_message)

        conn.commit()
        msg = "The email has been sent!"

    return render_template("send-promo.html", msg=msg, session=session)


@app.route('/bait-editor', methods=['GET', 'POST'])
def bait_editor():
    login_status = require_login_status(must_be_admin=True, destination='bait-editor')
    if login_status is not None:
        return login_status

    msg = ''

    cursor = conn.cursor()

    if request.method == 'POST':
        # collect data from html form
        insert_name = request.form['insert-name']
        insert_availability = 'insert-availability' in request.form
        insert_description = request.form['insert-description']

        # if name exists
        if insert_name:
            cursor.execute('SELECT * FROM bait WHERE name = ?', (insert_name,))
            found_bait = cursor.fetchone()

            if found_bait:
                cursor.execute('UPDATE bait SET availability = ? WHERE name = ?',
                               (int(insert_availability), insert_name))

                if insert_description:
                    cursor.execute('UPDATE bait SET description = ? WHERE name = ?', (insert_description, insert_name))

                msg = 'Updated bait %s.' % insert_name
            else:
                cursor.execute('INSERT INTO bait (name, availability, description) VALUES (?, ?, ?)',
                               (insert_name, int(insert_availability), insert_description))
                msg = 'Added new bait %s.' % insert_name

        # remove items
        remove_name = request.form['remove-name']

        if remove_name:
            cursor.execute('DELETE FROM bait WHERE name = ?', (remove_name,))
            msg = 'Removed bait %s.' % remove_name

    # fetch current bait table
    cursor.execute('SELECT * FROM bait')
    baits = cursor.fetchall()
    conn.commit()

    return render_template("bait-editor.html", session=session, msg=msg, baits=baits)


@app.route('/bait')
def live_bait():
    must_be_available = request.args.get('available', default='false') == "true"

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM bait' + (' WHERE availability = 1' if must_be_available else ''))
    baits = cursor.fetchall()
    baits.sort(key=lambda x: x['name'])

    return render_template("bait.html", session=session, baits=baits)


@app.route('/brand-editor', methods=['GET', 'POST'])
def brand_editor():
    login_status = require_login_status(must_be_admin=True, destination='brand-editor')
    if login_status is not None:
        return login_status

    msg = ''

    cursor = conn.cursor()

    if request.method == 'POST':
        # insert/modify items:
        insert_logo = request.files.getlist('insert-logo')[0]
        insert_logo_name = insert_logo.filename
        insert_name = request.form.get('insert-name')
        insert_description = request.form.get('insert-description')

        if insert_name:
            cursor.execute('SELECT * FROM brands WHERE name = ?', (insert_name,))
            found_brand = cursor.fetchone()

            if found_brand:
                if insert_logo_name:
                    cursor.execute('UPDATE brands SET logo = ? WHERE name = ?', (insert_logo_name, insert_name))

                if insert_description:
                    cursor.execute('UPDATE brands SET description = ? WHERE name = ?',
                                   (insert_description, insert_name))

                msg = 'Updated brand %s.' % insert_name
            else:
                cursor.execute('INSERT INTO brands (logo, name, description) VALUES (?, ?, ?)',
                               (insert_logo_name, insert_name, insert_description))
                msg = 'Added new brand %s.' % insert_name

            # upload logo to brands folder
            if insert_logo:
                # create brands folder if it doesn't already exist
                if not os.path.exists("static/images/brands"):
                    os.mkdir("static/images/brands")

                insert_logo.save("static/images/brands/" + insert_logo_name)

        # remove items
        remove_name = request.form.get('remove-name')

        if remove_name:
            cursor.execute('DELETE FROM brands WHERE name = ?', (remove_name,))
            msg = 'Removed brand %s.' % remove_name

    # fetch current brand table
    cursor.execute('SELECT * FROM brands')
    brands = cursor.fetchall()

    conn.commit()

    return render_template("brand-editor.html", session=session, msg=msg, brands=brands)


@app.route('/brands')
def brands_list():
    sort = request.args.get('sort', default='random')

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM brands')
    brands = cursor.fetchall()

    if sort == 'alphabetical':
        brands.sort(key=lambda x: x['name'])
    else:
        random.shuffle(brands)

    return render_template("brands.html", session=session, brands=brands)


@app.route('/community')
def community():
    count = int(request.args.get('count', default='10'))
    page = int(request.args.get('page', default='1'))

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM community ORDER BY [date] DESC')
    posts = cursor.fetchall()

    if len(posts) > 0:
        pagerange = range(max(1, page - 3), min(math.ceil(len(posts) / count), page + 3) + 1)
    else:
        pagerange = [1]

    return render_template("community.html", session=session, count=count, page=page, pagerange=pagerange, posts=posts, datetime=datetime, len=len, min=min, ceil=math.ceil)

@app.route('/delete_post', methods=['POST'])
def delete_post():
    if 'admin' in session:
        post_id = request.form.get('post_id')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM community WHERE id = ?', (post_id,) )
        return redirect(url_for('community'))
    else:
        abort(403)

@app.route('/submit-post', methods=['GET', 'POST'])
def submit_post():
    login_status = require_login_status(destination='submit-post')
    if login_status is not None:
        return login_status

    msg = ''

    cursor = conn.cursor()

    if request.method == 'POST':
        image = request.files.getlist('image')[0]
        image_type = image.filename[image.filename.rfind('.'):]

        if image:
            new_image_name = format(random.getrandbits(64), '016x') + image_type
        else:
            new_image_name = None

        text = request.form.get('text')

        if image or text:
            cursor.execute('INSERT INTO community (image, text, usr, date) VALUES (?, ?, ?, ?)', (new_image_name, text, session['username'], math.floor(time.time())))
            msg = 'Post submitted.'

            # upload image to community folder
            if image:
                # create community folder if it doesn't already exist
                if not os.path.exists("static/images/community"):
                    os.mkdir("static/images/community")

                image.save("static/images/community/" + new_image_name)
        else:
            msg = 'Please add either an image or text to your post.'

    conn.commit()

    return render_template("submit-post.html", session=session, msg=msg)


@app.route('/shop-editor', methods=['GET', 'POST'])
def shop_editor():
    login_status = require_login_status(must_be_admin=True, destination='shop-editor')
    if login_status is not None:
        return login_status

    msg = ''

    cursor = conn.cursor()

    if request.method == 'POST':
        # insert/modify items:
        insert_image = request.files.getlist('insert-image')[0]
        insert_image_name = insert_image.filename
        insert_name = request.form.get('insert-name')
        insert_product_id = request.form.get('insert-product-ID')
        insert_provider = request.form.get('insert-provider')
        insert_description = request.form['insert-description']
        insert_price = request.form.get('insert-price')

        if insert_name:
            cursor.execute('SELECT * FROM products WHERE product_name = ?', (insert_name,))
            found_product = cursor.fetchone()
            if found_product:
                cursor.execute('UPDATE products SET product_provider = ? WHERE product_name = ?', (insert_provider, insert_name))
                if insert_description:
                    cursor.execute('UPDATE products SET product_description = ? WHERE product_name = ?', (insert_description, insert_name))
                if insert_price:
                    cursor.execute('UPDATE products SET price = ? WHERE product_name = ?', (float(insert_price), insert_name))
                msg = 'Updated product %s.' % insert_name
            else:
                if insert_price:
                    cursor.execute('INSERT INTO products (product_name, product_provider, product_description, price, product_image) VALUES (?, ?, ?, ?, ?)',
                                   (insert_name, insert_provider, insert_description, float(insert_price), insert_image_name))
                    msg = 'Added new product %s.' % insert_name
                else:
                    msg = 'Please add item price.'
            if insert_image:
                # create brands folder if it doesn't already exist
                if not os.path.exists("static/images/products"):
                    os.mkdir("static/images/products")

                insert_image.save("static/images/products/" + insert_image_name)
        # remove items
        remove_name = request.form['remove-name']

        if remove_name:
            cursor.execute('DELETE FROM products WHERE product_name = ?', (remove_name,))
            msg = 'Removed product %s.' % remove_name

    # fetch current product table
    cursor.execute('SELECT * FROM products')
    products = cursor.fetchall()

    conn.commit()

    return render_template("shop-editor.html", session=session, msg=msg, products=products)


@app.route('/shop')
def shop():

    sort = request.args.get('sort', default='default')
    count = int(request.args.get('count', default='10'))
    page = int(request.args.get('page', default='1'))

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products')
    products = cursor.fetchall()
    if len(products)>0:
        product_ids = [product['product_id'] for product in products]
        ratings = {}

        for id in product_ids:
            ratings[id] = average_product_rating(cursor, id)

        pagerange = range(max(1, page - 3), min(math.ceil(len(products)/count), page+3) + 1)
        if sort == 'price':
            products.sort(key=lambda x: x['price'])
        elif sort == 'rating':
            products.sort(key=lambda x: -average_product_rating(cursor, x['product_id']))
        else:
            products.sort(key=lambda x: x['product_id'])

        return render_template("shop.html", session=session, sort=sort, count=count, page=page, pagerange=pagerange, products=products, ratings=ratings, len=len, min=min, ceil=math.ceil)
    return "Shop is empty please come back later!"

@app.route('/product/<product_id>', methods=['GET', 'POST'])
def product(product_id):
    msg = ''

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products WHERE PRODUCT_ID = ?', (product_id,))
    focused_product = cursor.fetchone()
    found_rating = None

    if 'loggedin' in session.keys():
        cursor.execute('SELECT * FROM ratings WHERE usr = ? AND product = ?', (session['username'], product_id,))
        found_rating = cursor.fetchone()

    if found_rating:
        user_rating = found_rating['rating']
    else:
        user_rating = None

    if focused_product is None:
        abort(404)

    if request.method == 'POST':
        user_rating = request.form.get('user-rating')
        quantity = request.form.get('quantity')
        add_to_cart = request.form.get('add-to-cart')
        print(add_to_cart)

        if 'loggedin' in session.keys() and user_rating:
            if found_rating:
                cursor.execute('UPDATE ratings SET rating = ? WHERE usr = ? AND product = ?', (user_rating, session['username'], product_id))
            else:
                cursor.execute('INSERT INTO ratings (usr, product, rating) VALUES (?, ?, ?)', (session['username'], product_id, user_rating))

            conn.commit()

            msg = 'Rating updated.'

        if 'loggedin' in session.keys() and add_to_cart:
            cursor.execute('SELECT * FROM cart WHERE username = ? AND product_id = ?', (session['username'], product_id))
            found_cart_item = cursor.fetchone()
            print(found_cart_item)

            if found_cart_item:
                cursor.execute('UPDATE cart SET quantity = ? WHERE username = ? AND product_id = ?', (found_cart_item['quantity']+int(quantity), session['username'], product_id))
            else:
                cursor.execute('INSERT INTO cart (username, product_id, quantity) VALUES (?, ?, ?)', (session['username'], product_id, quantity))

            conn.commit()

            msg = 'Added item(s) to cart.'

    return render_template("product.html", session=session, msg=msg, focused_product=focused_product, rating=average_product_rating(cursor, product_id), user_rating=user_rating)


@app.route('/cart', methods=['GET', 'POST'])
def cart():
    login_status = require_login_status(destination='cart')
    if login_status is not None:
        return login_status

    msg = ''

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM cart')

    cursor.execute('SELECT products.product_id, products.product_name, products.price, cart.quantity FROM cart INNER JOIN products ON cart.product_id = products.product_id WHERE username = ?', (session['username'],))
    cart_items = cursor.fetchall()
    total = sum([product['price']*product['quantity'] for product in cart_items])

    remove_product_id = request.form.get('remove-id')
    email_receipt = request.form.get('email-receipt')

    if remove_product_id:
        cursor.execute('DELETE FROM cart WHERE username = ? AND product_id = ?', (session['username'], remove_product_id))
        conn.commit()

        return redirect(url_for('cart'))

    if email_receipt:
        send_receipt(session['username'])
        msg = 'Receipt sent. You may need to check your Spam folder.'

    return render_template("cart.html", session=session, msg=msg, cart=cart_items, total=total)


@app.route('/fishingSpots', methods=['GET', 'POST'])
def fishingSpots():
    lat = []
    long = []
    label = []

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM markedFishingSpots')
    spot = cursor.fetchone()
    while spot is not None:
        lat.append(spot['latitude'])
        long.append(spot['longitude'])
        label.append(spot['label'])
        spot = cursor.fetchone()

    locations = '['
    count = 0
    while count < len(label):
        locations += '{"lat":' + str(lat[count]) + ',"long":' + str(long[count]) + ',"label":"' + str(
            label[count]) + '"},'
        count += 1
    locations = locations[:-1]
    locations += ']'

    return render_template("fishingSpots.html", locations=locations)


@app.route('/map-editor', methods=['GET', 'POST'])
def map_editor():
    login_status = require_login_status(must_be_admin=True, destination='map-editor')
    if login_status is not None:
        return login_status

    msg = ''

    cursor = conn.cursor()

    if request.method == 'POST':
        # insert/modify items:
        insert_label = request.form['insert-label']
        insert_longitude = request.form['insert-long']
        insert_latitude = request.form['insert-lat']

        if insert_label:
            cursor.execute('SELECT * FROM markedFishingSpots WHERE label = ?', (insert_label,))
            found_label = cursor.fetchone()

            if found_label:
                cursor.execute('UPDATE markedFishingSpots SET longitude = ? WHERE label = ?',
                               (insert_longitude, insert_label))

                if insert_latitude:
                    cursor.execute('UPDATE markedFishingSpots SET latitude = ? WHERE label = ?',
                                   (insert_latitude, insert_label))
                msg = 'Updated marker %s.' % insert_label
            else:
                cursor.execute('INSERT INTO markedFishingSpots (latitude, longitude, label) VALUES (?, ?, ?)',
                               (insert_latitude, insert_longitude, insert_label))
                msg = 'Added new marker %s.' % insert_label

        # remove marker
        remove_marker = request.form['remove-label']

        if remove_marker:
            cursor.execute('DELETE FROM markedFishingSpots WHERE label = ?', (remove_marker,))
            msg = 'Removed marker %s.' % remove_marker

    # fetch current marker table
    cursor.execute('SELECT * FROM markedFishingSpots')
    markers = cursor.fetchall()

    conn.commit()

    return render_template("map-editor.html", session=session, msg=msg, markers=markers)


@app.route('/home')
def home_redirect():
    return redirect('/')


@app.route('/login', methods=['GET', 'POST'])
def login():
    destination = request.args.get('destination', default='profile')

    login_status = require_login_status(must_be_logged_out=True, destination=destination)
    if login_status is not None:
        return login_status

    msg = ''

    # check if username and password were received
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'destination' in request.form:
        username = request.form['username']
        password = request.form['password']
        destination = request.form['destination']

        # Check if account exists using MySQL - Grabs from userdata table on Azure SQL Server
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM userdata WHERE username = ?', (username,))

        # Fetch one record and return result
        account = cursor.fetchone()

        if account:
            try:
                # verifies that input password, after salting+hashing, matches the hash in the database, and throws an error if not
                hasher.verify(account['password'], password)

                # since the default parameters for argon2 will likely change over time, use this opportunity to update the database using the latest set of parameters since we do have the plaintext password at this moment
                if (hasher.check_needs_rehash(account['password'])):
                    cursor.execute('UPDATE userdata SET password = ? WHERE username = ?;', (hasher.hash(password), username))

                # Create session data, we can access this data in other routes
                session['loggedin'] = True
                session['id'] = account['id']
                session['username'] = account['username']

                # add admin attribute to session if user is an admin
                session['admin'] = bool(account['admin'])

                # Redirect to desired page (profile by default)
                return redirect('/' + destination)
            except:
                # Invalid password
                msg = 'Incorrect username/password!'
        else:
            # Account doesn't exist
            msg = 'Incorrect username/password!'
            # Show the login form with message (if any)
    return render_template('login.html', destination=destination, session=session, msg=msg)


@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('username', None)
    session.pop('admin', None)
    return redirect(url_for('home'))


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    login_status = require_login_status()
    if login_status is not None:
        return login_status

    cursor = conn.cursor()
    cursor.execute('SELECT * FROM userdata WHERE username = ?', (session['username'],))
    account = cursor.fetchone()

    username = session['username']
    email = account['email']
    phone = account['phone']
    email_consent = account['email_consent']

    if request.method == 'POST':
        email_consent = 'consent' in request.form
        cursor.execute('UPDATE userdata SET email_consent = ? WHERE username = ?;', (int(email_consent), username))
        conn.commit()

    return render_template("profile.html", session=session, username=username, email=email, phone=phone,
                           email_consent=email_consent)


@app.route('/register', methods=['GET', 'POST'])
def register():
    login_status = require_login_status(must_be_logged_out=True)
    if login_status is not None:
        return login_status

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
        if request.form.get('consent'):  # 1 yes 0 no
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
            # create hash for the password
            hashed_password = hasher.hash(password)

            # Account doesn't exist and the form data is valid, now insert new account into accounts table
            cursor.execute('INSERT INTO userdata VALUES ( ?, ?, ?, ?, ?, ?, ?)',
                           (username, hashed_password, email, consent, phone, 0, math.floor(time.time())))

            # today sets the account creation date, zero is for not admin

            conn.commit()
            msg = 'You have successfully registered!'

    elif request.method == 'POST':
        # Form is empty... (no POST data)
        msg = 'Please fill out the form!'
    # Show registration form with message (if any)
    return render_template('register.html', session=session, msg=msg)


if __name__ == '__main__':
    app.run()
