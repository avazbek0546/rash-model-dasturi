"""Botning «/» komandalar menyusi (rolga mos).

Ro'yxat bitta joyda saqlanadi: `main.py` ishga tushganda va `/admins` paneli
orqali **yangi admin qo'shilganda** (`handlers/admin_manage.py`) shu yerdan
olinadi — ikki joyda takrorlanmasligi uchun alohida modulga chiqarilgan.
"""

from __future__ import annotations

from aiogram.types import BotCommand

#: Oddiy o'quvchi ko'radigan komandalar.
BASE_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="Asosiy menyu"),
    BotCommand(command="app", description="Imtihon ilovasini ochish"),
    BotCommand(command="tahlil", description="Test tahlili va yechimlar"),
    BotCommand(command="help", description="Yordam"),
)

#: O'qituvchi (admin) uchun qo'shimcha komandalar.
ADMIN_COMMANDS: tuple[BotCommand, ...] = BASE_COMMANDS + (
    BotCommand(command="new_exam", description="Yangi imtihon yaratish"),
    BotCommand(command="exams", description="Imtihonlar ro'yxati"),
    BotCommand(command="stats", description="Umumiy statistika"),
    BotCommand(command="report", description="PDF natijalar hisoboti"),
    BotCommand(command="add_solution", description="Yechim yuklash"),
    BotCommand(command="itemstats", description="Savollar statistikasi"),
    BotCommand(command="admins", description="Adminlarni boshqarish"),
)
