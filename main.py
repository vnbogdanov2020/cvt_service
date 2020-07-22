import urllib3, json, requests, keyboards
from setting import bot_token, chat_id_service, rest_link_product, rest_link_store, rest_link_stock
import telebot
from telebot import types
import barcode
import time, datetime, schedule
from configparser import ConfigParser
import os
from os import path
from mysql.connector import MySQLConnection, Error
from multiprocessing import Process, freeze_support
#from service import transliterate

urllib3.disable_warnings()

bot = telebot.TeleBot(bot_token)

dirpath = os.path.dirname(__file__)
conffile = os.path.join(dirpath, 'config.ini')

#Чтение файла конфигурации
def read_db_config(filename=conffile, section='mysql'):
    parser = ConfigParser()
    parser.read(filename)
    db = {}
    if parser.has_section(section):
        items = parser.items(section)
        for item in items:
            db[item[0]] = item[1]
    else:
        raise Exception('{0} not found in the {1} file'.format(section, filename))
    return db

#Первый запуск
@bot.message_handler(commands=['start'])
def start_message(message):
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()

    sql = ("SELECT * FROM users WHERE chat_id= %s")
    cursor.execute(sql, [(message.from_user.id)])
    user = cursor.fetchone()
    if not user:
        bot.send_message(message.chat.id, 'Вы впервые здесь. Для продолжения нажмите кнопку "Зарегистрироваться"', reply_markup=keyboards.NewUser)
    else:
        bot.send_message(message.chat.id, 'С возвращением!', reply_markup=keyboards.keyboard1)
    cursor.close()
    conn.close()

#Регистрация пользователя
@bot.message_handler(content_types=['contact'])
def add_user(message):
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()

    sql = ("SELECT * FROM users WHERE chat_id= %s")
    cursor.execute(sql, [(message.contact.user_id)])
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user:
        newdata = (message.contact.user_id,
               message.contact.first_name,
               message.contact.last_name,
               message.contact.phone_number,
               datetime.datetime.now()
               )
        db_config = read_db_config()
        conn = MySQLConnection(**db_config)
        cursor = conn.cursor()
        cursor.executemany("INSERT INTO users (chat_id, first_name, last_name, phone_number,datetime) VALUES (%s,%s,%s,%s,%s)",
                           (newdata,))
        conn.commit()
        cursor.close()
        conn.close()
        bot.send_message(message.chat.id, 'Приятно познакомиться, можете пользоваться сервисом', reply_markup=keyboards.keyboard1)

#Обработка сообщений
@bot.message_handler(content_types=['text'])
def send_text(message):
    if message.text.lower() == 'поиск':
        products(message.chat.id)
    elif message.text.lower() == 'локация':
        city = get_user_city(message.chat.id)
        if city:
            usercity=city
        else:
            usercity='???'

        citykeyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=1)
        #citykeyboard.add(types.KeyboardButton(text='Выбрать город ('+usercity+')'),
        citykeyboard.add(types.KeyboardButton(text='Выбрать город ('+usercity+')'),
                         types.KeyboardButton(text='Обновить координаты', request_location=True))
        citykeyboard.add(types.KeyboardButton(text='Назад'))
        bot.send_message(message.chat.id, 'Чтобы увидеть товар в ближайших аптеках, выберите город и обновите координаты', reply_markup=citykeyboard)
    elif message.text.lower() == 'назад':
        bot.send_message(message.chat.id, 'Главное меню', reply_markup=keyboards.keyboard1)
    elif message.text.lower().find('выбрать город') == 0:
        try:
            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()

            cursor.execute('select city from store s group by city order by city')
            citys = cursor.fetchall()
            markup = types.InlineKeyboardMarkup()
            for city in citys:
                name = city[0]
                switch_button = types.InlineKeyboardButton(text=name, callback_data='mycity:'+name)
                markup.add(switch_button)

            cursor.close()
            conn.close()

            bot.send_message(message.chat.id, "Выберите ваш город", reply_markup=markup)
            #bot.send_message(message.chat.id, 'Главное меню', reply_markup=keyboards.keyboard1)

            #bot.send_message(message.chat.id, todos['name'] + chr(10) + chr(10) + 'Цена: ' + todos['price'] + ' тенге')
        except requests.exceptions.ConnectionError:
            bot.send_message(message.chat.id, 'Отсутствует связь с сервисом цен')
            #Оповестить сервис о проблемах
            bot.send_message(chat_id_service, 'Внимание! Проблема с доступом к сервису цен')


    #Регистрация местоположения
@bot.message_handler(content_types=['location'])
def send_location(message):
    print(message)
    newdata = (
               message.location.latitude,
               message.location.longitude,
               message.from_user.id
               )
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()

    cursor.executemany("UPDATE users SET latitude = %s, longitude = %s WHERE chat_id = %s",
                       (newdata,))
    conn.commit()
    cursor.close()
    conn.close()

    bot.send_message(message.chat.id, 'Ваши координаты обновлены')

#Получение фото товара
@bot.message_handler(content_types=['photo'])
def sent_barcode(message):
    raw = message.photo[2].file_id
    file_info = bot.get_file(raw)
    downloaded_file = 'https://api.telegram.org/file/bot' + bot_token + '/' + file_info.file_path
    bcode = barcode.read_barcode(downloaded_file,message.chat.id)
    print(str(bcode))

    if bcode == 'No':
        bot.send_message(message.chat.id, 'Не удалось распознать код. Попробуйте еще раз')
    else:
         print(bcode.decode())



#Формирование результатов поиска
@bot.inline_handler(func=lambda query: len(query.query) >= 2)
def query_text(query):
        offset = int(query.offset) if query.offset else 0
        try:

            SQL = """\
                    select t.nommodif, t.name, t.producer, t.photo, t.city, case when %s='' then 0 ELSE t.price end price
                    FROM (SELECT p1.nommodif, p1.name, p1.producer, p1.photo, p3.city, p2.price FROM product p1
                    inner join stock p2 on p2.company = p1.company and p2.product_id = p1.nommodif
                    inner join store p3 on p3.company = p2.company and p3.name = p2.store
                    WHERE lower(concat(p1.name,COALESCE(p1.search_key,''))) LIKE lower(%s)
                    group by p1.nommodif, p1.name, p1.producer, p1.photo, p3.city, p2.price) t
                    WHERE (t.city = %s or %s='') LIMIT 5 OFFSET %s
                    """
            SQL2 = """\
                                SELECT p1.nommodif, p1.name, p1.producer, p1.photo, p3.city,
                                case when min(p2.price) <> max(p2.price) then
                                CONCAT(min(p2.price),' - ',max(p2.price))
                                else
                                CONCAT(min(p2.price))
                                end 
                                price  FROM product p1
                                inner join users u on u.chat_id = %s
                                inner join stock p2 on p2.company = p1.company and p2.product_id = p1.nommodif
                                inner join store p3 on p3.company = p2.company and p3.name = p2.store and p3.city = u.city
                                WHERE lower(concat(p1.name,p1.producer,COALESCE(p1.search_key,''))) LIKE lower(%s)
                                group by p1.nommodif, p1.name, p1.producer, p1.photo, p3.city
                                LIMIT 5 OFFSET %s
                                """
            #cursor.execute(SQL, (usercity,'%'+query.query+'%',usercity,usercity,offset,))
            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()

            cursor.execute(SQL2, (query.from_user.id, '%' + query.query + '%', offset,))

            products = cursor.fetchall()

            results = []
            try:
                m_next_offset = str(offset + 5) if len(products) == 5 else None
                if products:
                    for product in products:
                        try:
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton(text=u'\U0001F4CC Добавить в список', callback_data='prlist:' + str(product[0])),
                                       types.InlineKeyboardButton(text='Мой список', callback_data='mylist:'),)
                            markup.add(types.InlineKeyboardButton(text=u'\U0001F30D Искать по списку в аптеках', callback_data='locallist:'),)
                                #types.InlineKeyboardButton(text=u'\U0001F30D Найти аптеку', callback_data='local:'+str(product[0])),
                                #types.InlineKeyboardButton(text=u'\U0001F30D', callback_data='locallist:'),
                            markup.add(types.InlineKeyboardButton(text=u'\U0001F50D Продолжить поиск', switch_inline_query_current_chat=""),)

                            items = types.InlineQueryResultArticle(
                                id=product[0], title=product[1],
                                description="Производитель: "+product[2]+"\nЦена: "+str(product[5])+" тенге",
                                input_message_content=types.InputTextMessageContent(
                                    message_text='*'+product[1]+'* [.](' + product[3] + ') \n'+product[2]+'\nЦена: '+str(product[5])+' тенге',
                                    parse_mode='markdown',
                                    disable_web_page_preview=False,
                                     ),
                                reply_markup=markup,
                                thumb_url=product[3], thumb_width=100, thumb_height=100
                            )
                            results.append(items)
                        except Exception as e:
                            print(e)
                    cursor.close()
                    conn.close()
                    bot.answer_inline_query(query.id, results, next_offset=m_next_offset if m_next_offset else "", cache_time=86400)
                    #bot.answer_inline_query(query.id, results, next_offset=m_next_offset if m_next_offset else "")
                else:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(
                        types.InlineKeyboardButton(text=u'\U0001F50D Продолжить поиск', switch_inline_query_current_chat=""),
                    )
                    items = types.InlineQueryResultArticle(
                        id='1000', title='Ничего не найдено',
                        description="Попробуйте изменить запрос...",
                        input_message_content=types.InputTextMessageContent(
                            message_text="По вашему запросу ничего не найдено. Попробуйте изменить запрос...",
                            parse_mode='markdown',
                            disable_web_page_preview=True,
                        ),
                        reply_markup=markup,
                        thumb_url='https://ru.seaicons.com/wp-content/uploads/2017/02/Cute-Ball-Stop-icon.png',
                        thumb_width=100, thumb_height=100
                    )
                    results.append(items)
                    bot.answer_inline_query(query.id, results)
                add_logs(query.from_user.id, 'search', query.query)
            except Exception as e:
                print(e)

        except Exception as e:
            print(e)



#Обработка входящих сообщений
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    # Если сообщение из чата с ботом
    if call.message:
        #print(call)
        if call.data.find('mycity:') == 0:
            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET city = %s WHERE chat_id = %s', (call.data.replace('mycity:',''),call.from_user.id))
            conn.commit()
            cursor.close()
            conn.close()

            #cursor.close()
            #cnx.close()
            usercity = call.data.replace('mycity:','')
            citykeyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=1)
            citykeyboard.add(types.KeyboardButton(text='Выбрать город ('+usercity+')'),
                             types.KeyboardButton(text='Обновить координаты', request_location=True))
            citykeyboard.add(types.KeyboardButton(text='Назад'))

            bot.send_message(call.from_user.id,
                             'Ваш город: '+usercity,
                             reply_markup=citykeyboard)
        if call.data.find('mylist:') == 0:
            get_search_list(call.from_user.id)
        if call.data.find('clearlist:') == 0:
            #Очистка списка пользоателя
            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM user_product_list WHERE chat_id = %s', [(call.from_user.id)])
            conn.commit()
            cursor.close()
            conn.close()
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton(text=u'\U0001F50D Продолжить поиск', switch_inline_query_current_chat=""), )
            bot.send_message(call.from_user.id,
                             'Ваш список товаров удален.', reply_markup=markup)

        if call.data.find('refresh:') == 0:
            #Импорт данных из аптек
            import_product()
            import_store()
            import_stock()
        if call.data.find('locallist:') == 0:
            search_list(call.from_user.id)
        if call.data.find('locallist_one:') == 0:
            search_list_one(call.from_user.id)
        if call.data.find('prlist:') == 0:
            add_list(call.from_user.id, call.data.replace('prlist:',''), call.id)

    # Если сообщение из инлайн-режима
    elif call.inline_message_id:
        if call.data.find('prlist:') == 0:
            add_list(call.from_user.id, call.data.replace('prlist:',''), call.id)
        elif call.data.find('locallist:') == 0:
            get_search_list(call.from_user.id)
            search_list(call.from_user.id)
        elif call.data.find('mylist:') == 0:
            get_search_list(call.from_user.id)

def products(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text=u'\U0001F4CC' + ' Мой список', callback_data='mylist:'),)
    markup.add(types.InlineKeyboardButton(text=u'\U0001F50D' + ' Поиск товаров', switch_inline_query_current_chat=""),)

    # Сервисная комманда
    if user_id == chat_id_service:
        markup.add(
            types.InlineKeyboardButton(text='Обновить данные', callback_data='refresh:'))
    bot.send_message(user_id, "КАК ЭТО РАБОТАЕТ:\n\n"
                                      "1. В пункте [Локация] выберите город и обновите координаты (если Вы еще этого не сделали)\n\n"
                                      "2. Нажмите [\U0001F50DПоиск], наберите боту часть наименования, например '@goAptoBot анальгин' или просто отправьте боту \U0001F4CE ФОТО ШТРИХ-КОДА с упаковки товара\n\n"
                                      "3. Найдите один или несколько товаров и добавьте их в список \U0001F4CC \n\n"
                                      "4. Нажмите [\U0001F30D Искать по списку в аптеках] - бот сообщит о цене и найдет ближайшие к вам аптеки, в которых есть товар из списка",
                     parse_mode='HTML', reply_markup=markup)

def add_logs(user_id, metod, value):
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()
    now = datetime.datetime.now()
    cursor.executemany("INSERT INTO logs (datetime,chat_id,metod,value) VALUES (%s,%s,%s,%s)",
                       [(now,int(user_id), metod,value),])
    conn.commit()
    cursor.close()
    conn.close()

def add_list(user_id, in_data, call_id):
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()

    cursor.executemany("INSERT INTO user_product_list (chat_id, product_id) VALUES (%s,%s)",
                       [(int(user_id), str(in_data)),])
    conn.commit()
    cursor.close()
    conn.close()

    add_logs(int(user_id), 'product', str(in_data))

    bot.answer_callback_query(call_id, show_alert=True, text="Товар добавлен в список")

#Получение города пользователяя
def get_user_city(in_user_id):
    # Ищем город пользователя
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()
    sql = ("SELECT city FROM users WHERE chat_id = %s")
    cursor.execute(sql, [(in_user_id)])
    city = cursor.fetchone()
    cursor.close()
    conn.close()
    if city:
        return city[0]
    else:
        return ''

#Вывод списка товаров
def get_search_list(user_id):
    try:
        product_list = 'СПИСОК ДЛЯ ПОИСКА:\n\n'
        db_config = read_db_config()
        conn = MySQLConnection(**db_config)
        cursor = conn.cursor()
        sql = (
            "SELECT p2.name, p2.producer FROM user_product_list p1, product p2 WHERE p2.nommodif = p1.product_id AND p1.chat_id = %s group by p2.name, p2.producer order by p2.name")
        cursor.execute(sql, [(user_id)])
        products = cursor.fetchall()

        for product in products:
            product_list = product_list + '*' + product[0] + '*' + '\n' + product[1] + '\n' + '\n'

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text=u'\U0001F5D1 Очистить список', callback_data='clearlist:'),)
        markup.add(types.InlineKeyboardButton(text=u'\U0001F30D Искать по списку в аптеках', callback_data='locallist:'),)
        markup.add(types.InlineKeyboardButton(text=u'\U0001F50D Продолжить поиск', switch_inline_query_current_chat=""),)

        bot.send_message(user_id,
                         product_list,
                         parse_mode='markdown',
                         reply_markup=markup, )

        cursor.close()
        conn.close()
    except Exception as e:
        print(e)
        bot.send_message(user_id,
                         'Список пустой...')

#Поиск товаров по списку
def search_list(user_id):
    #Назначим кнопки
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text=u'\U0001F30D Искать каждый товар отдельно', callback_data='locallist_one:'),)
    markup.add(types.InlineKeyboardButton(text=u'\U0001F50D Продолжить поиск', switch_inline_query_current_chat=""), )
    #Проверим что в списке есть товары
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()

    SQL = 'select count(distinct(product_id)) from user_product_list where chat_id = %s'
    cursor.execute(SQL, (user_id,))
    products = cursor.fetchone()

    if products[0]==0:
        bot.send_message(user_id,
                         'Сначала добавьте товары в список для поиска')
        cursor.close()
        conn.close()
    else:
        #Ищем аптеки с поответствием по списку товара
        db_config = read_db_config()
        conn = MySQLConnection(**db_config)
        cursor = conn.cursor()

        SQL = """\
                    SELECT s.name, s.address, s.mode, s.phone, s.latitude ,s.longitude, t.way FROM (
                    SELECT count(p2.product_id) kol, p1.name, get_way(p1.latitude ,p1.longitude,u.latitude,u.longitude) way FROM users u
                    inner join store p1 on p1.city = u.city 
                    inner join stock p2 on p2.company = p1.company and p1.name = p2.store 
                    WHERE u.chat_id = %s and p2.product_id in (select distinct(product_id) from user_product_list where chat_id = %s)
                    group by p1.name,  p1.latitude ,p1.longitude,u.latitude,u.longitude having count(p2.product_id)=(select count(distinct(product_id)) from user_product_list where chat_id = %s)
                    ) t 
                    inner join store s on s.name = t.name
                    order by t.way asc 
                    LIMIT 3
                    """
        cursor.execute(SQL, (user_id, user_id, user_id,))
        stores = cursor.fetchall()

        for store in stores:
            try:
                bot.send_venue(user_id,
                               store[4],
                               store[5],
                               store[0] + ' (' + str(store[6]) + ' м.)',
                               store[1]
                               )
                bot.send_message(user_id,
                                 store[2] + '\n' + 'Тел: ' + store[3] + '\nЕсть все по списку',
                                 parse_mode='markdown', )
            except Exception as e:
                print(e)
        cursor.close()
        conn.close()
        bot.send_message(user_id,
                         'Если вас не устроили эти аптеки, вы можете поискать отдельно каждый товар из списка в ближайших аптеках',
                         parse_mode='markdown',
                         reply_markup=markup, )

def search_list_one(user_id):
    #Назначим кнопки
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(text=u'\U0001F30D Искать каждый товар отдельно', callback_data='locallist_one:'),
    )
    #Проверим что в списке есть товары
    db_config = read_db_config()
    conn = MySQLConnection(**db_config)
    cursor = conn.cursor()

    SQL = 'select count(distinct(product_id)) from user_product_list where chat_id = %s'
    cursor.execute(SQL, (user_id,))
    products = cursor.fetchone()

    if products[0]==0:
        bot.send_message(user_id,
                         'Сначала добавьте товары в список для поиска')
        cursor.close()
        conn.close()
    else:
        #Ищем аптеки с поответствием по списку товара
        db_config = read_db_config()
        conn = MySQLConnection(**db_config)
        cursor = conn.cursor()

        SQL = """\
                    select r.name, r.producer, p3.name, p3.address, p3.mode, p3.latitude, p3.longitude, p3.phone, t.way, t.price from  user_product_list p
                    inner join product r on r.nommodif = p.product_id 
                    inner join users u on u.chat_id = p.chat_id 
                    inner join store p3 on p3.city = u.city and r.company = p3.company
                    inner join 
                    (
                    select distinct(pl.product_id) product_id, p2.price, min(get_way(p3.latitude ,p3.longitude,u.latitude,u.longitude)) way from user_product_list pl
                    inner join users u on u.chat_id = pl.chat_id 
                    inner join stock p2 on p2.product_id = pl.product_id
                    inner join store p3 on p3.company = p2.company and p3.name = p2.store and p3.city = u.city
                    where pl.chat_id = %s
                    group by pl.product_id, p2.price
                    ) t
                    where p.chat_id = %s
                    and get_way(p3.latitude ,p3.longitude,u.latitude,u.longitude)=t.way and r.nommodif = t.product_id
                    group by r.name, r.producer, p3.name, p3.address, p3.mode, p3.latitude, p3.longitude, p3.phone, t.way, t.price
                    """
        cursor.execute(SQL, (user_id, user_id, ))
        stores = cursor.fetchall()

        for store in stores:
            try:
                bot.send_venue(user_id,
                               store[5],
                               store[6],
                               store[2] + ' (' + str(store[8]) + ' м.)',
                               store[3]
                               )
                bot.send_message(user_id,
                                 '*'+store[0]+'*\n'+store[1]+'\n'+'Цена: '+str(store[9])+' тенге\n\n'+
                                 store[4] + '\n' + 'Тел: ' + store[7] ,
                                 parse_mode='markdown', )
            except Exception as e:
                print(e)
        cursor.close()
        conn.close()

def import_data():
    import_product()
    import_store()
    import_stock()


def import_product():
    #Импорт справочника товаров
    try:
        response = requests.get(rest_link_product, verify=False)
        if response.status_code == 404:
            bot.send_message(chat_id_service, 'Не оступен сервер ЦВЕТНАЯ')
        else:
            todos = json.loads(response.text)
            indata = []

            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM product WHERE company='ЦВЕТНАЯ'")

            for row in todos['items']:
                indata.append((
                        'ЦВЕТНАЯ',
                        row['nommodif'],
                        row['modif_name'],
                        row['producer'],
                        row['barcode'],
                        row['photo'],
                        row['skey'],
                ))


            '''
            try:
                while todos['next']['$ref']:
                    newlink = todos['next']['$ref']
                    print(newlink)
                    response = requests.get(newlink, verify=False)
                    todos = json.loads(response.text)
                    for row in todos['items']:
                        indata.append((
                            'ЦВЕТНАЯ',
                            row['nommodif'],
                            row['modif_name'],
                            row['producer'],
                            row['barcode']
                        ))
            '''
            cursor.executemany("INSERT INTO product (company,nommodif,name,producer,barcode,photo,search_key) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                               indata)

            conn.commit()
            cursor.close()
            conn.close()

            bot.send_message(chat_id_service, 'Справочник товаров обновлен')
            #cursor.close()
            #cnx.close()
    except requests.exceptions.ConnectionError:
        # Оповестить сервис о проблемах
        bot.send_message(chat_id_service, 'Внимание! Проблема с доступом к сервису цен')

def import_store():
    #Импорт справочника аптек
    try:
        response = requests.get(rest_link_store, verify=False)
        if response.status_code == 404:
            bot.send_message(chat_id_service, 'Не доступен сервер ЦВЕТНАЯ')
        else:
            todos = json.loads(response.text)
            indata = []

            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM store WHERE company='ЦВЕТНАЯ'")

            for row in todos['items']:
                indata.append((
                    row['company'],
                    row['store'],
                    row['city'],
                    row['address'],
                    row['lon'],
                    row['lat'],
                    row['phone'],
                    row['resh']
                ))
            cursor.executemany(
                "INSERT INTO store (company,name,city,address,longitude,latitude,phone,mode) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                indata)

            conn.commit()
            cursor.close()
            conn.close()

            bot.send_message(chat_id_service, 'Справочник аптек обновлен')
            #cursor.close()
            #cnx.close()
    except requests.exceptions.ConnectionError:
        # Оповестить сервис о проблемах
        bot.send_message(chat_id_service, 'Внимание! Проблема с доступом к сервису цен')

def import_stock():
    #Импорт остатков
    try:
        response = requests.get(rest_link_stock, verify=False)
        if response.status_code == 404:
            bot.send_message(chat_id_service, 'Не оступен сервер ЦВЕТНАЯ')
        else:
            todos = json.loads(response.text)
            indata = []

            db_config = read_db_config()
            conn = MySQLConnection(**db_config)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM stock WHERE company='ЦВЕТНАЯ'")

            for row in todos['items']:
                indata.append((
                        'ЦВЕТНАЯ',
                        row['store'],
                        row['nommodif'],
                        row['restfact'],
                        row['price']
                ))
            try:
                while todos['next']['$ref']:
                    newlink = todos['next']['$ref']
                    print(newlink)
                    response = requests.get(newlink, verify=False)
                    todos = json.loads(response.text)
                    for row in todos['items']:
                        indata.append((
                            'ЦВЕТНАЯ',
                            row['store'],
                            row['nommodif'],
                            row['restfact'],
                            row['price']
                        ))
            except Exception as e:
                print(e)
            cursor.executemany("INSERT INTO stock (company,store,product_id,qnt,price) VALUES (%s,%s,%s,%s,%s)",
                               indata)

            conn.commit()
            cursor.close()
            conn.close()

            bot.send_message(chat_id_service, 'Остатки обновлены')
            #cursor.close()
            #cnx.close()
    except requests.exceptions.ConnectionError:
        # Оповестить сервис о проблемах
        bot.send_message(chat_id_service, 'Внимание! Проблема с доступом к сервису цен')

# Подключаем планировщик повторений
#schedule.every().day.at("05:00").do(job)
#schedule.every().hour.do(import_data)
"""
schedule.every(10).minutes.do(import_data)


# это функция проверки на запуск импорта
def check_import_data():
    while True:
        schedule.run_pending()
        time.sleep(60)

# а теперь запускаем проверку в отдельном потоке
if __name__ == '__main__':
    freeze_support()
    p1 = Process(target=check_import_data, args=())
    p1.start()

"""
while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(e)
        # повторяем через 15 секунд в случае недоступности сервера Telegram
        time.sleep(15)


