"""
Schools.by Telegram Bot
Telegram бот для доступа к функциям schools.by
"""

import os
import asyncio
from typing import Dict, Optional
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
import logging

from schools_api import SchoolsAPI, SchoolsAPIError

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
WAITING_LOGIN, WAITING_PASSWORD = range(2)

class SchoolsBot:
    """Основной класс Telegram бота для schools.by"""
    
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.user_sessions = {}  # Хранилище сессий пользователей
        self.setup_handlers()
    
    def setup_handlers(self):
        """Настройка обработчиков команд и сообщений"""
        
        # Обработчик для команды /start
        self.application.add_handler(CommandHandler("start", self.start_command))
        
        # Обработчик для команды /help
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # ConversationHandler для аутентификации
        auth_handler = ConversationHandler(
            entry_points=[CommandHandler("login", self.login_command)],
            states={
                WAITING_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_login)],
                WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_password)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)]
        )
        self.application.add_handler(auth_handler)
        
        # Обработчики для основных функций
        self.application.add_handler(CommandHandler("schedule", self.schedule_command))
        self.application.add_handler(CommandHandler("grades", self.grades_command))
        self.application.add_handler(CommandHandler("homework", self.homework_command))
        self.application.add_handler(CommandHandler("announcements", self.announcements_command))
        self.application.add_handler(CommandHandler("profile", self.profile_command))
        self.application.add_handler(CommandHandler("logout", self.logout_command))
        
        # Обработчик callback queries (inline кнопки)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Обработчик неизвестных команд
        self.application.add_handler(MessageHandler(filters.COMMAND, self.unknown_command))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        welcome_message = f"""
🏫 Добро пожаловать в Schools.tg, {user.first_name}!

Этот бот позволяет получать доступ к вашим данным из системы schools.by:
📅 Расписание занятий
📊 Оценки
📝 Домашние задания
📢 Объявления

Для начала работы войдите в систему командой /login

Доступные команды:
/help - Список всех команд
/login - Войти в систему schools.by
/schedule - Посмотреть расписание
/grades - Посмотреть оценки
/homework - Посмотреть домашние задания
/announcements - Посмотреть объявления
/profile - Информация о профиле
/logout - Выйти из системы
        """
        
        keyboard = [
            [InlineKeyboardButton("🔑 Войти в систему", callback_data="login")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_message = """
🔧 Доступные команды:

🔑 Аутентификация:
/login - Войти в систему schools.by
/logout - Выйти из системы

📚 Основные функции:
/schedule - Посмотреть расписание занятий
/grades - Посмотреть оценки
/homework - Посмотреть домашние задания
/announcements - Посмотреть объявления
/profile - Информация о профиле

ℹ️ Справка:
/help - Показать это сообщение
/start - Начать работу с ботом

📝 Примечания:
• Для работы с данными необходимо войти в систему
• Бот безопасно хранит ваши данные только в течение сессии
• Для выхода используйте команду /logout
        """
        await update.message.reply_text(help_message)
    
    async def login_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса аутентификации"""
        user_id = update.effective_user.id
        
        if user_id in self.user_sessions:
            await update.message.reply_text(
                "Вы уже вошли в систему! Используйте /logout для выхода."
            )
            return ConversationHandler.END
        
        await update.message.reply_text(
            "🔑 Вход в систему schools.by\n\n"
            "Введите ваш логин (имя пользователя):\n\n"
            "Для отмены используйте команду /cancel"
        )
        return WAITING_LOGIN
    
    async def handle_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода логина"""
        username = update.message.text.strip()
        context.user_data['username'] = username
        
        await update.message.reply_text(
            f"Логин принят: {username}\n\n"
            "Теперь введите ваш пароль:"
        )
        return WAITING_PASSWORD
    
    async def handle_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода пароля и попытка аутентификации"""
        password = update.message.text.strip()
        username = context.user_data.get('username')
        user_id = update.effective_user.id
        
        # Удаляем сообщение с паролем из чата для безопасности
        try:
            await update.message.delete()
        except:
            pass
        
        await update.message.reply_text("🔄 Проверяем данные для входа...")
        
        try:
            # Создаем API клиент и пытаемся аутентифицироваться
            async with SchoolsAPI() as api:
                auth_result = await api.authenticate(username, password)
                
                # Проверяем результат аутентификации
                if isinstance(auth_result, dict) and not auth_result.get('success', False):
                    error_msg = auth_result.get('error', 'Неизвестная ошибка')
                    await update.message.reply_text(
                        f"❌ Ошибка входа: {error_msg}\n\n"
                        "Проверьте правильность логина и пароля.\n"
                        "Попробуйте снова: /login"
                    )
                    return ConversationHandler.END
                
                # Сохраняем данные пользователя
                self.user_sessions[user_id] = {
                    'username': username,
                    'authenticated': True,
                    'auth_data': auth_result
                }
            
            keyboard = [
                [InlineKeyboardButton("📅 Расписание", callback_data="schedule")],
                [InlineKeyboardButton("📊 Оценки", callback_data="grades")],
                [InlineKeyboardButton("📝 Домашние задания", callback_data="homework")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            success_msg = auth_result.get('message', 'Успешная аутентификация')
            await update.message.reply_text(
                f"✅ {success_msg}\n"
                f"Пользователь: {username}\n\n"
                "Теперь вы можете использовать все функции бота:",
                reply_markup=reply_markup
            )
            
        except SchoolsAPIError as e:
            await update.message.reply_text(
                f"❌ Ошибка входа: {str(e)}\n\n"
                "Проверьте правильность логина и пароля.\n"
                "Попробуйте снова: /login"
            )
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при входе в систему.\n"
                "Попробуйте позже или обратитесь к администратору."
            )
        
        return ConversationHandler.END
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущей операции"""
        await update.message.reply_text(
            "❌ Операция отменена.\n"
            "Используйте /start для возврата к главному меню."
        )
        return ConversationHandler.END
    
    def _check_authentication(self, user_id: int) -> bool:
        """Проверка аутентификации пользователя"""
        session = self.user_sessions.get(user_id)
        return session and session.get('authenticated', False)
    
    def _get_user_credentials(self, user_id: int) -> Optional[tuple]:
        """Получение данных пользователя для аутентификации"""
        session = self.user_sessions.get(user_id)
        if session and session.get('authenticated'):
            return session.get('username'), session.get('auth_data')
        return None
    
    async def schedule_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение расписания"""
        user_id = update.effective_user.id
        
        if not self._check_authentication(user_id):
            await update.message.reply_text(
                "🔐 Для просмотра расписания необходимо войти в систему.\n"
                "Используйте команду /login"
            )
            return
        
        try:
            await update.message.reply_text("📅 Получаем расписание...")
            
            # Создаем новую сессию API для каждого запроса
            async with SchoolsAPI() as api:
                schedule = await api.get_schedule()
                
                if isinstance(schedule, dict) and 'html' not in schedule:
                    # Если получили структурированные данные
                    schedule_text = "📅 **Расписание занятий:**\n\n"
                    schedule_text += str(schedule)
                else:
                    # Для демонстрации работы бота показываем пример расписания
                    username = self.user_sessions[user_id].get('username', 'Пользователь')
                    schedule_text = f"""📅 **Расписание для {username}**

📆 Понедельник:
• 09:00-09:45 Математика
• 10:00-10:45 Русский язык
• 11:00-11:45 История

📆 Вторник:
• 09:00-09:45 Физика
• 10:00-10:45 Химия
• 11:00-11:45 Биология

⚠️ Это пример данных. Для получения реального расписания необходима доработка API."""
                
                await update.message.reply_text(schedule_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Schedule error: {e}")
            await update.message.reply_text("❌ Ошибка при получении расписания.")
    
    async def grades_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение оценок"""
        user_id = update.effective_user.id
        
        if not self._check_authentication(user_id):
            await update.message.reply_text(
                "🔐 Для просмотра оценок необходимо войти в систему.\n"
                "Используйте команду /login"
            )
            return
        
        try:
            await update.message.reply_text("📊 Получаем оценки...")
            
            # Показываем пример оценок для демонстрации
            username = self.user_sessions[user_id].get('username', 'Пользователь')
            grades_text = f"""📊 **Оценки для {username}**

📚 Математика: 9, 8, 9, 10
📖 Русский язык: 8, 9, 8, 9
🌍 География: 10, 9, 10, 9
🔬 Физика: 8, 8, 9, 8
⚗️ Химия: 9, 8, 9, 9
🌿 Биология: 9, 10, 9, 8

🎆 Средний балл: 8.9

⚠️ Это пример данных. Для получения реальных оценок необходима доработка API."""
            
            await update.message.reply_text(grades_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Grades error: {e}")
            await update.message.reply_text("❌ Ошибка при получении оценок.")
    
    async def homework_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение домашних заданий"""
        user_id = update.effective_user.id
        
        if not self._check_authentication(user_id):
            await update.message.reply_text(
                "🔐 Для просмотра домашних заданий необходимо войти в систему.\n"
                "Используйте команду /login"
            )
            return
        
        try:
            await update.message.reply_text("📝 Получаем домашние задания...")
            
            username = self.user_sessions[user_id].get('username', 'Пользователь')
            homework_text = f"""📝 **Домашние задания для {username}**

📚 Математика:
• Решить задачи № 15-20 (стр. 45)
• К среде 22.09

📖 Русский язык:
• Написать сочинение на тему "Моя мечта"
• К пятнице 24.09

🔬 Физика:
• Изучить параграф 3.2
• Решить задачу № 12
• К четвергу 23.09

⚠️ Это пример данных. Для получения реальных домашних заданий необходима доработка API."""
            
            await update.message.reply_text(homework_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Homework error: {e}")
            await update.message.reply_text("❌ Ошибка при получении домашних заданий.")
    
    async def announcements_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение объявлений"""
        user_id = update.effective_user.id
        
        if not self._check_authentication(user_id):
            await update.message.reply_text(
                "🔐 Для просмотра объявлений необходимо войти в систему.\n"
                "Используйте команду /login"
            )
            return
        
        try:
            await update.message.reply_text("📢 Получаем объявления...")
            
            announcements_text = """📢 **Объявления**

🎯 **Важно!** Родительское собрание
📅 25 сентября 2023 г. в 18:00
🏠 В актовом зале школы

🎭 **Осенний концерт**
📅 28 сентября 2023 г. в 16:00
🎤 Открытые репетиции каждую среду

🏆 **Олимпиада по математике**
📅 5 октября 2023 г.
📝 Регистрация до 30 сентября

⚠️ Это пример данных. Для получения реальных объявлений необходима доработка API."""
            
            await update.message.reply_text(announcements_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Announcements error: {e}")
            await update.message.reply_text("❌ Ошибка при получении объявлений.")
    
    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение профиля пользователя"""
        user_id = update.effective_user.id
        
        if not self._check_authentication(user_id):
            await update.message.reply_text(
                "🔐 Для просмотра профиля необходимо войти в систему.\n"
                "Используйте команду /login"
            )
            return
        
        try:
            await update.message.reply_text("👤 Получаем данные профиля...")
            
            username = self.user_sessions[user_id].get('username', 'Пользователь')
            school = self.user_sessions[user_id].get('school', 'Образовательное учреждение')
            
            profile_text = f"""👤 **Профиль ученика**

👨‍🎓 **Имя:** {username}
🏠 **Школа:** {school}
📚 **Класс:** 9А
🎆 **Учебный год:** 2023-2024

📊 **Текущая статистика:**
• Средний балл: 8.4
• Пропусков: 3 дня
• Опозданий: 1 раз

🔧 **Доступные функции:**
• 📅 Расписание (/schedule)
• 📊 Оценки (/grades)
• 📝 Домашние задания (/homework)
• 📢 Объявления (/announcements)

⚠️ Это пример данных. Для получения реальных данных профиля необходима доработка API."""
            
            await update.message.reply_text(profile_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Profile error: {e}")
            await update.message.reply_text("❌ Ошибка при получении профиля.")
    
    async def logout_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Выход из системы"""
        user_id = update.effective_user.id
        
        if user_id in self.user_sessions:
            # Удаляем сессию пользователя
            del self.user_sessions[user_id]
            
            await update.message.reply_text(
                "✅ Вы успешно вышли из системы.\n"
                "Используйте /login для повторного входа."
            )
        else:
            await update.message.reply_text(
                "ℹ️ Вы не были авторизованы в системе."
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback queries от inline кнопок"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "login":
            await query.message.reply_text(
                "🔑 Используйте команду /login для входа в систему."
            )
        elif data == "help":
            await self.help_command(update, context)
        elif data == "schedule":
            await self.schedule_command(update, context)
        elif data == "grades":
            await self.grades_command(update, context)
        elif data == "homework":
            await self.homework_command(update, context)
    
    async def unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик неизвестных команд"""
        await update.message.reply_text(
            "❓ Неизвестная команда.\n"
            "Используйте /help для просмотра доступных команд."
        )
    
    def run(self):
        """Запуск бота"""
        print("🚀 Запускаем Schools.by Telegram Bot...")
        print("Бот готов к работе! Найдите его в Telegram и отправьте /start")
        print("Для остановки нажмите Ctrl+C")
        self.application.run_polling()


def main():
    """Главная функция запуска бота"""
    # Получаем токен бота из переменных окружения
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token or token == 'YOUR_BOT_TOKEN_HERE':
        print("❌ Ошибка: не установлен TELEGRAM_BOT_TOKEN")
        print("")
        print("Инструкции по настройке:")
        print("1. Перейдите к @BotFather в Telegram")
        print("2. Создайте бота командой /newbot")
        print("3. Скопируйте токен")
        print("4. Откройте файл .env и замените YOUR_BOT_TOKEN_HERE на ваш токен")
        print("5. Запустите бота снова: python bot.py")
        return
    
    # Создаем и запускаем бота
    try:
        bot = SchoolsBot(token)
        bot.run()
    except KeyboardInterrupt:
        print("\n✅ Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")


if __name__ == '__main__':
    main()