# -*- coding: utf-8 -*-
"""
Created on Sun May  3 23:09:41 2020

@author: User
"""
import telebot
from telebot import types

keyboard1 = telebot.types.ReplyKeyboardMarkup(resize_keyboard=1)
keyboard1.row('Настройка','Операции')


keyboard2 = telebot.types.ReplyKeyboardMarkup(resize_keyboard=1)
keyboard2.add(types.KeyboardButton(text='Фото рецепта'))
keyboard2.add(types.KeyboardButton(text='Назад'))

#keyboard1.row('Привет', 'Пока','Я тебя люблю')
#keyboard1.row('Запрос')

NewUser = telebot.types.ReplyKeyboardMarkup(resize_keyboard=1)
key_b = types.KeyboardButton(text='Зарегистрироваться',request_contact=True)
NewUser.add(key_b)

