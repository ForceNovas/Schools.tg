"""
Schools.by API Client
Модуль для работы с API schools.by
"""

import requests
import asyncio
import httpx
from typing import Dict, List, Optional
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import json


class SchoolsAPIError(Exception):
    """Исключение для ошибок API Schools.by"""
    pass


class SchoolsAPI:
    """Клиент для работы с Schools.by API"""
    
    def __init__(self, base_url: str = "https://schools.by"):
        self.base_url = base_url
        self.session = None
        self.cookies = {}
        self.csrf_token = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = httpx.AsyncClient(
            headers=self.headers,
            timeout=30.0,
            follow_redirects=True,
            cookies=httpx.Cookies()
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.aclose()
    
    def _build_url(self, endpoint: str) -> str:
        """Построение полного URL для endpoint"""
        return urljoin(self.base_url, endpoint)
    
    async def _make_request(self, method: str, endpoint: str, allow_errors: bool = False, **kwargs) -> Dict:
        """Выполнение HTTP запроса к API"""
        if not self.session:
            raise SchoolsAPIError("Session not initialized. Use async context manager.")
        
        url = self._build_url(endpoint)
        
        try:
            response = await self.session.request(method, url, **kwargs)
            content_type = response.headers.get('Content-Type', '')
            text = response.text
            
            if response.status_code == 200:
                if 'application/json' in content_type:
                    return response.json()
                else:
                    # Попытка найти JSON в HTML
                    json_data = self._extract_json_from_html(text)
                    if json_data and 'html' not in json_data:
                        return json_data
                    else:
                        return {'html': text, 'status': response.status_code}
                        
            elif allow_errors:
                # Возвращаем данные даже при ошибках
                return {
                    'html': text, 
                    'status': response.status_code,
                    'error': True,
                    'url': str(response.url)
                }
            else:
                # Проверяем, есть ли полезная информация в ошибке
                if response.status_code == 500 and 'html' in content_type:
                    return {'html': text, 'status': response.status_code, 'error': True}
                raise SchoolsAPIError(f"HTTP {response.status_code}: {text[:200]}...")
        
        except httpx.RequestError as e:
            if allow_errors:
                return {'error': str(e), 'client_error': True}
            raise SchoolsAPIError(f"Request failed: {str(e)}")
    
    def _extract_json_from_html(self, html: str) -> Dict:
        """Извлечение JSON данных из HTML страницы"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Поиск скриптов с данными
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                content = script.string.strip()
                # Поиск различных паттернов JSON данных
                if 'window.' in content or 'var ' in content:
                    # Попытка извлечь JSON из JavaScript переменных
                    lines = content.split('\n')
                    for line in lines:
                        if 'data' in line.lower() or 'config' in line.lower():
                            try:
                                # Простой парсинг JSON из строки
                                if '{' in line and '}' in line:
                                    start = line.find('{')
                                    end = line.rfind('}') + 1
                                    json_str = line[start:end]
                                    return json.loads(json_str)
                            except (json.JSONDecodeError, ValueError):
                                continue
        
        return {"html": html}  # Возвращаем HTML если JSON не найден
    
    async def get_csrf_token(self, html: str) -> Optional[str]:
        """Извлечение CSRF токена из HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Ищем CSRF токен в различных местах
        csrf_inputs = [
            soup.find('input', {'name': 'csrfmiddlewaretoken'}),
            soup.find('input', {'name': '_token'}),
            soup.find('input', {'name': 'csrf_token'}),
            soup.find('meta', {'name': 'csrf-token'})
        ]
        
        for csrf_input in csrf_inputs:
            if csrf_input:
                token = csrf_input.get('value') or csrf_input.get('content')
                if token:
                    return token
        
        # Ищем в скриптах
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                content = script.string
                if 'csrf' in content.lower() or 'token' in content.lower():
                    # Простой поиск токена в JavaScript
                    token_patterns = [
                        r'csrf[_\-]?token["\']?\s*[:=]\s*["\']([a-zA-Z0-9\-_]+)["\']',
                        r'_token["\']?\s*[:=]\s*["\']([a-zA-Z0-9\-_]+)["\']'
                    ]
                    for pattern in token_patterns:
                        match = re.search(pattern, content, re.IGNORECASE)
                        if match:
                            return match.group(1)
        
        return None
    
    async def authenticate(self, username: str, password: str) -> Dict:
        """
        Аутентификация пользователя в системе schools.by
        
        Args:
            username: Имя пользователя (логин)
            password: Пароль
            
        Returns:
            Dict: Результат аутентификации
        """
        try:
            # Шаг 1: Получаем главную страницу для инициализации сессии
            main_response = await self.session.get(self._build_url('/'))
            
            # Шаг 2: Получаем страницу логина
            login_response = await self.session.get(self._build_url('/login'))
            
            if login_response.status_code != 200:
                raise SchoolsAPIError(f"Cannot access login page: HTTP {login_response.status_code}")
            
            login_html = login_response.text
            soup = BeautifulSoup(login_html, 'html.parser')
            
            # Шаг 3: Анализируем форму авторизации
            form = soup.find('form')
            if not form:
                raise SchoolsAPIError("Login form not found on the page")
            
            # Получаем action URL формы
            form_action = form.get('action', '/login')
            if not form_action.startswith('http'):
                form_action = self._build_url(form_action)
            
            # Шаг 4: Извлекаем CSRF токен
            csrf_token = await self.get_csrf_token(login_html)
            
            # Шаг 5: Подготавливаем данные формы
            form_data = {}
            
            # Собираем все скрытые поля
            hidden_inputs = form.find_all('input', {'type': 'hidden'})
            for hidden_input in hidden_inputs:
                name = hidden_input.get('name')
                value = hidden_input.get('value', '')
                if name:
                    form_data[name] = value
            
            # Находим поля для логина и пароля
            username_field = None
            password_field = None
            
            # Обычные имена полей
            possible_username_names = ['username', 'login', 'email', 'user', 'login_name']
            possible_password_names = ['password', 'pass', 'pwd']
            
            input_fields = form.find_all('input')
            for inp in input_fields:
                name = inp.get('name', '').lower()
                input_type = inp.get('type', '').lower()
                
                if not username_field and (name in possible_username_names or input_type == 'email'):
                    username_field = inp.get('name')
                elif not password_field and (name in possible_password_names or input_type == 'password'):
                    password_field = inp.get('name')
            
            if not username_field or not password_field:
                raise SchoolsAPIError(f"Cannot find login fields. Found: username={username_field}, password={password_field}")
            
            # Добавляем учетные данные
            form_data[username_field] = username
            form_data[password_field] = password
            
            # Добавляем CSRF токен если найден
            if csrf_token:
                # Пробуем разные имена для CSRF токена
                csrf_names = ['csrfmiddlewaretoken', '_token', 'csrf_token']
                csrf_name = None
                
                for inp in hidden_inputs:
                    if inp.get('name') in csrf_names:
                        csrf_name = inp.get('name')
                        break
                
                if csrf_name:
                    form_data[csrf_name] = csrf_token
            
            print(f"Отправляем форму с полями: {list(form_data.keys())}")
            
            # Шаг 6: Отправляем данные аутентификации
            auth_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': self._build_url('/login'),
                'Origin': self.base_url
            }
            
            # Объединяем заголовки
            combined_headers = {**self.session.headers, **auth_headers}
            
            auth_response = await self.session.post(
                form_action,
                data=form_data,
                headers=auth_headers
            )
            
            print(f"Ответ аутентификации: {auth_response.status_code}")
            
            # Шаг 7: Анализируем результат
            if auth_response.status_code == 200:
                # Проверяем, есть ли признаки успешной аутентификации
                response_text = auth_response.text
                
                # Проверяем наличие ошибок в ответе
                soup_result = BeautifulSoup(response_text, 'html.parser')
                error_elements = soup_result.find_all(['div', 'span', 'p'], class_=lambda x: x and ('error' in x.lower() or 'alert' in x.lower()))
                
                if error_elements:
                    error_text = ' '.join([elem.get_text().strip() for elem in error_elements])
                    return {
                        'success': False,
                        'error': f'Authentication failed: {error_text}',
                        'status': auth_response.status_code
                    }
                
                # Если нет явных ошибок, считаем аутентификацию успешной
                return {
                    'success': True,
                    'message': 'Authentication successful',
                    'status': auth_response.status_code,
                    'cookies': dict(self.session.cookies)
                }
            
            elif auth_response.status_code in [302, 303, 307]:
                # Редирект может означать успешную аутентификацию
                location = auth_response.headers.get('Location', '')
                if '/login' not in location.lower():
                    return {
                        'success': True,
                        'message': 'Authentication successful (redirected)',
                        'status': auth_response.status_code,
                        'redirect': location,
                        'cookies': dict(self.session.cookies)
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Authentication failed (redirected back to login)',
                        'status': auth_response.status_code
                    }
            
            else:
                return {
                    'success': False,
                    'error': f'Authentication failed: HTTP {auth_response.status_code}',
                    'status': auth_response.status_code,
                    'response': auth_response.text[:500]
                }
            
        except Exception as e:
            raise SchoolsAPIError(f"Authentication failed: {str(e)}")
    
    async def get_user_info(self) -> Dict:
        """Получение информации о пользователе"""
        return await self._make_request('GET', '/profile')
    
    async def get_schedule(self, date: Optional[str] = None) -> Dict:
        """
        Получение расписания
        
        Args:
            date: Дата в формате YYYY-MM-DD (если не указана, то текущая)
            
        Returns:
            Dict: Расписание занятий
        """
        endpoint = '/schedule'
        params = {}
        if date:
            params['date'] = date
        
        return await self._make_request('GET', endpoint, params=params)
    
    async def get_grades(self, period: Optional[str] = None) -> Dict:
        """
        Получение оценок
        
        Args:
            period: Период (например, 'quarter', 'semester', 'year')
            
        Returns:
            Dict: Оценки по предметам
        """
        endpoint = '/grades'
        params = {}
        if period:
            params['period'] = period
        
        return await self._make_request('GET', endpoint, params=params)
    
    async def get_homework(self, date: Optional[str] = None) -> Dict:
        """
        Получение домашних заданий
        
        Args:
            date: Дата в формате YYYY-MM-DD
            
        Returns:
            Dict: Домашние задания
        """
        endpoint = '/homework'
        params = {}
        if date:
            params['date'] = date
        
        return await self._make_request('GET', endpoint, params=params)
    
    async def get_announcements(self) -> Dict:
        """Получение объявлений"""
        return await self._make_request('GET', '/announcements')
    
    async def search_schools(self, query: str) -> List[Dict]:
        """
        Поиск школ через scraping
        
        Args:
            query: Поисковый запрос
            
        Returns:
            List[Dict]: Список найденных школ
        """
        # Поскольку /search не работает, используем комбинированный подход
        schools = []
        
        try:
            # 1. Пробуем главную страницу
            main_page = await self._make_request('GET', '/', allow_errors=True)
            if 'html' in main_page:
                soup = BeautifulSoup(main_page['html'], 'html.parser')
                
                # Ищем ссылки на поддомены школ
                links = soup.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text().strip()
                    
                    # Поиск ссылок на поддомены
                    if ('.schools.by' in href and 'http' in href) or href.startswith('/subdomains'):
                        if text and len(text) > 3 and query.lower() in text.lower():
                            schools.append({
                                'name': text,
                                'url': href,
                                'type': 'main_page_link'
                            })
            
            # 2. Пробуем страницу subdomains
            subdomains = await self.get_subdomains_page()
            for school in subdomains:
                if query.lower() in school['name'].lower():
                    schools.append(school)
            
            # 3. Проверяем отдельные страницы
            test_pages = ['/capabilities', '/help', '/about']
            for page in test_pages:
                try:
                    result = await self._make_request('GET', page, allow_errors=True)
                    if 'html' in result:
                        soup = BeautifulSoup(result['html'], 'html.parser')
                        links = soup.find_all('a', href=True)
                        
                        for link in links:
                            href = link.get('href', '')
                            text = link.get_text().strip()
                            
                            if ('.schools.by' in href or href.startswith('http')) and text:
                                if query.lower() in text.lower() and len(text) > 3:
                                    schools.append({
                                        'name': text,
                                        'url': href,
                                        'type': f'from_{page}',
                                        'source': page
                                    })
                except:
                    continue
            
            # Удаляем дубликаты по URL
            seen_urls = set()
            unique_schools = []
            for school in schools:
                if school['url'] not in seen_urls:
                    seen_urls.add(school['url'])
                    unique_schools.append(school)
            
            return unique_schools[:15]  # Ограничиваем результат
            
        except Exception as e:
            print(f"Search error: {e}")
            return schools  # Возвращаем частичные результаты


    async def discover_endpoints(self) -> Dict:
        """Исследование доступных endpoints"""
        endpoints = {
            'working': [],
            'failing': [],
            'redirects': []
        }
        
        # Список возможных endpoints для проверки
        test_endpoints = [
            '/', '/login', '/registration', '/help', '/about',
            '/capabilities', '/cost', '/contact', '/news',
            '/subdomains', '/api', '/mobile', '/app'
        ]
        
        for endpoint in test_endpoints:
            try:
                url = self._build_url(endpoint)
                response = await self.session.get(url, follow_redirects=False)
                if response.status_code == 200:
                    endpoints['working'].append({
                        'endpoint': endpoint,
                        'status': response.status_code,
                        'content_type': response.headers.get('Content-Type', '')
                    })
                elif response.status_code in [301, 302, 303, 307, 308]:
                    endpoints['redirects'].append({
                        'endpoint': endpoint,
                        'status': response.status_code,
                        'location': response.headers.get('Location', '')
                    })
                else:
                    endpoints['failing'].append({
                        'endpoint': endpoint,
                        'status': response.status_code
                    })
            except Exception as e:
                endpoints['failing'].append({
                    'endpoint': endpoint,
                    'error': str(e)
                })
        
        return endpoints
    
    async def get_subdomains_page(self) -> List[Dict]:
        """Получение списка поддоменов школ с страницы /subdomains"""
        try:
            result = await self._make_request('GET', '/subdomains', allow_errors=True)
            if 'html' in result:
                soup = BeautifulSoup(result['html'], 'html.parser')
                
                schools = []
                # Ищем все ссылки на школы
                links = soup.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text().strip()
                    
                    # Проверяем, что это ссылка на поддомен школы
                    if ('.schools.by' in href or 'schools.by/' in href) and text and len(text) > 3:
                        schools.append({
                            'name': text,
                            'url': href,
                            'type': 'subdomain'
                        })
                
                return schools
            
            return []
            
        except Exception as e:
            print(f"Subdomains page error: {e}")
            return []
    
    async def analyze_login_form(self) -> Dict:
        """Анализ формы авторизации"""
        try:
            result = await self._make_request('GET', '/login')
            if 'html' in result:
                soup = BeautifulSoup(result['html'], 'html.parser')
                
                # Ищем форму авторизации
                form = soup.find('form')
                if form:
                    form_data = {
                        'action': form.get('action', ''),
                        'method': form.get('method', 'POST'),
                        'fields': []
                    }
                    
                    # Находим все поля ввода
                    inputs = form.find_all(['input', 'textarea', 'select'])
                    for inp in inputs:
                        field_info = {
                            'name': inp.get('name', ''),
                            'type': inp.get('type', ''),
                            'value': inp.get('value', ''),
                            'required': inp.has_attr('required')
                        }
                        form_data['fields'].append(field_info)
                    
                    return form_data
            
            return {'error': 'No form found'}
            
        except Exception as e:
            return {'error': str(e)}


# Пример использования для тестирования API endpoints
async def test_api():
    """Функция для тестирования различных API endpoints"""
    async with SchoolsAPI() as api:
        try:
            print("=== Исследование Schools.by API ===")
            
            # Открытие доступных endpoints
            print("\n1. Проверка endpoints...")
            endpoints = await api.discover_endpoints()
            
            print(f"✓ Работающие endpoints: {len(endpoints['working'])}")
            for ep in endpoints['working']:
                print(f"  - {ep['endpoint']} ({ep['status']})")
            
            if endpoints['failing']:
                print(f"\n✗ Неработающие endpoints: {len(endpoints['failing'])}")
                for ep in endpoints['failing'][:5]:  # Показываем первые 5
                    if 'error' in ep:
                        print(f"  - {ep['endpoint']}: {ep['error']}")
                    else:
                        print(f"  - {ep['endpoint']} ({ep['status']})")
            
            # Анализ формы авторизации
            print("\n2. Анализ формы авторизации...")
            login_form = await api.analyze_login_form()
            if 'error' not in login_form:
                print(f"✓ Найдена форма: {login_form['method']} -> {login_form['action']}")
                print(f"  Поля ввода: {len(login_form['fields'])}")
                for field in login_form['fields']:
                    if field['name']:
                        print(f"    - {field['name']} ({field['type']})")
            else:
                print(f"✗ Ошибка анализа формы: {login_form['error']}")
            
            # Получение списка школ
            print("\n3. Поиск школ...")
            schools = await api.get_subdomains_page()
            if schools:
                print(f"✓ Найдено школ на странице subdomains: {len(schools)}")
                for school in schools[:5]:  # Показываем первые 5
                    print(f"  - {school['name']}: {school['url']}")
            else:
                print("✗ Не удалось найти школы")
            
            # Попытка альтернативного поиска
            print("\n4. Альтернативный поиск...")
            alt_schools = await api.search_schools("минск")
            print(f"✓ Найдено ссылок: {len(alt_schools)}")
            
        except SchoolsAPIError as e:
            print(f"API Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    # Запуск тестирования API
    asyncio.run(test_api())