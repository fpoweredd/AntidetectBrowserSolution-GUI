import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional
import asyncio
from profile_manager.manager import ProfileManager
from loguru import logger
import requests
import json
from urllib.parse import urlparse
import time
from profile_manager.structures import ASocksSettings

# Кэш для хранения результатов проверки IP
proxy_info_cache = {}

class CreateProfileDialog:
    def __init__(self, parent, current_name=None):
        self.result = None
        self.dialog = tk.Toplevel(parent.root)
        self.dialog.title("Edit Profile" if current_name else "Create Profile")
        self.dialog.geometry("400x200")
        self.dialog.transient(parent.root)
        self.dialog.grab_set()
        
        # Применяем темную тему к диалогу
        self.dialog.configure(bg="#1a1a1a")
        
        # Profile name
        name_frame = ttk.Frame(self.dialog)
        name_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(name_frame, text="Profile Name:").pack(side=tk.LEFT)
        self.name_input = ttk.Entry(name_frame)
        self.name_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if current_name:
            self.name_input.insert(0, current_name)
        
        # Proxy type
        proxy_type_frame = ttk.Frame(self.dialog)
        proxy_type_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(proxy_type_frame, text="Proxy Type:").pack(side=tk.LEFT)
        self.proxy_type = ttk.Combobox(
            proxy_type_frame, 
            values=["http", "socks5"]
        )
        self.proxy_type.set("http")
        self.proxy_type.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Proxy string
        proxy_frame = ttk.Frame(self.dialog)
        proxy_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(
            proxy_frame, 
            text="Proxy (ip:port:login:pass):"
        ).pack(side=tk.LEFT)
        self.proxy_input = ttk.Entry(proxy_frame)
        self.proxy_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Добавляем поддержку CTRL+A
        def select_all(event):
            self.proxy_input.select_range(0, tk.END)
            return 'break'
            
        self.proxy_input.bind('<Control-a>', select_all)
        self.proxy_input.bind('<Control-A>', select_all)
        
        # Если редактируем профиль, подгружаем текущий прокси
        if current_name:
            profile = parent.manager.profiles.get(current_name)
            if profile and profile.proxy:
                # Устанавливаем тип прокси
                if profile.proxy.server.startswith('socks5'):
                    self.proxy_type.set("socks5")
                else:
                    self.proxy_type.set("http")
                    
                # Формируем строку прокси без протокола
                server = profile.proxy.server.split('://')[1]
                proxy_str = f"{server}:{profile.proxy.port}"
                if profile.proxy.username:
                    proxy_str += f":{profile.proxy.username}:{profile.proxy.password}"
                self.proxy_input.insert(0, proxy_str)
        
        # Buttons
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(
            button_frame, 
            text="Save", 
            command=self.accept
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            button_frame, 
            text="Cancel", 
            command=self.reject
        ).pack(side=tk.LEFT)
        
        self.dialog.wait_window()
    
    def accept(self):
        name = self.name_input.get().strip()
        if not name:
            messagebox.showwarning("Error", "Profile name cannot be empty")
            return
            
        proxy_str = self.proxy_input.get().strip()
        if not proxy_str:
            self.result = (name, None)
        else:
            proxy_type = self.proxy_type.get()
            self.result = (name, f"{proxy_type}://{proxy_str}")
        self.dialog.destroy()
    
    def reject(self):
        self.dialog.destroy()
    
    def get_profile_data(self) -> tuple[str, Optional[str]]:
        return self.result if self.result else ("", None)


def get_proxy_info(proxy_type: str, proxy_str: Optional[str]) -> str:
    if not proxy_type or not proxy_str:
        return "No proxy"
        
    # Проверяем кэш
    cache_key = f"{proxy_type}://{proxy_str}"
    if cache_key in proxy_info_cache:
        return proxy_info_cache[cache_key]
            
    try:
        parts = proxy_str.split(':')
        if len(parts) == 2:
            proxy_url = f"{proxy_type}://{parts[0]}:{parts[1]}"
        elif len(parts) == 4:
            proxy_url = f"{proxy_type}://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        else:
            return "Invalid"
            
        proxies = {'http': proxy_url, 'https': proxy_url}
        
        # Пробуем первый сервис
        try:
            response = requests.get(
                'http://ip-api.com/json/',
                proxies=proxies,
                timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    result = f"{data['query']} ({data['country']})"
                    proxy_info_cache[cache_key] = result
                    return result
        except Exception as e:
            logger.debug(f"First service failed: {e}")
            
        # Пробуем второй сервис
        try:
            response = requests.get(
                'https://api.ipify.org?format=json',
                proxies=proxies,
                timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                result = f"{data['ip']} (Unknown)"
                proxy_info_cache[cache_key] = result
                return result
        except Exception as e:
            logger.debug(f"Second service failed: {e}")
            
        return "No data"
    except Exception as e:
        logger.exception(f"Error getting proxy info: {e}")
        return "No data"


class SettingsDialog:
    def __init__(self, parent):
        self.result = None
        self.dialog = tk.Toplevel(parent.root)
        self.dialog.title("ASocks Settings")
        self.dialog.geometry("400x150")
        self.dialog.transient(parent.root)
        self.dialog.grab_set()
        
        # Применяем темную тему к диалогу
        self.dialog.configure(bg="#1a1a1a")
        
        # API Key
        api_frame = ttk.Frame(self.dialog)
        api_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(api_frame, text="API Key:").pack(side=tk.LEFT)
        self.api_input = ttk.Entry(api_frame)
        self.api_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Domain
        domain_frame = ttk.Frame(self.dialog)
        domain_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(domain_frame, text="Domain:").pack(side=tk.LEFT)
        self.domain_input = ttk.Entry(domain_frame)
        self.domain_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.domain_input.insert(0, "https://api.asocks.com")
        
        # Load current settings
        if parent.manager.asocks_settings:
            self.api_input.insert(0, parent.manager.asocks_settings.api_key)
            self.domain_input.insert(0, parent.manager.asocks_settings.domain)
        
        # Buttons
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(
            button_frame, 
            text="Save", 
            command=self.accept
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            button_frame, 
            text="Cancel", 
            command=self.reject
        ).pack(side=tk.LEFT)
        
        self.dialog.wait_window()
    
    def accept(self):
        api_key = self.api_input.get().strip()
        domain = self.domain_input.get().strip()
        if not api_key:
            messagebox.showwarning("Error", "API Key cannot be empty")
            return
        self.result = (api_key, domain)
        self.dialog.destroy()
    
    def reject(self):
        self.dialog.destroy()
    
    def get_settings(self) -> tuple[str, str]:
        return self.result if self.result else ("", "")


class MainWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Antidetect Browser")
        self.root.geometry("800x600")
        
        self.manager = ProfileManager()
        self.current_actions_frame = None
        
        # Создаем event loop для асинхронных операций
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.setup_ui()
        self.setup_dark_theme()
        
        # Обновление статуса каждую секунду
        self.update_profiles()
        self.root.after(1000, self.schedule_update)
        
        # Привязываем обработчик клика по всему окну
        self.root.bind('<Button-1>', self.on_root_click)
    
    def setup_ui(self):
        # Кнопки управления
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(
            button_frame, 
            text="Create Profile",
            command=self.create_profile
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            button_frame,
            text="Settings",
            command=self.show_settings
        ).pack(side=tk.LEFT, padx=5)
        
        # Таблица профилей
        columns = ("Name", "Status", "Proxy")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Привязываем обработчик клика по строке
        self.tree.bind('<Button-1>', self.on_tree_click)
    
    def setup_dark_theme(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Основные цвета
        bg_color = "#1a1a1a"
        fg_color = "white"
        button_bg = "#2a2a2a"
        button_fg = "white"
        selected_bg = "#2a82da"
        
        # Настройка основного окна
        self.root.configure(bg=bg_color)
        
        # Настройка Treeview
        style.configure(
            "Treeview",
            background=bg_color,
            foreground=fg_color,
            fieldbackground=bg_color
        )
        
        style.configure(
            "Treeview.Heading",
            background=button_bg,
            foreground=fg_color
        )
        
        style.map(
            "Treeview",
            background=[("selected", selected_bg)]
        )
        
        # Настройка кнопок
        style.configure(
            "TButton",
            background=button_bg,
            foreground=button_fg,
            padding=5
        )
        
        style.map(
            "TButton",
            background=[("active", selected_bg)],
            foreground=[("active", fg_color)]
        )
        
        # Настройка фреймов
        style.configure(
            "TFrame",
            background=bg_color
        )
        
        # Настройка лейблов
        style.configure(
            "TLabel",
            background=bg_color,
            foreground=fg_color
        )
        
        # Настройка Entry
        style.configure(
            "TEntry",
            fieldbackground=button_bg,
            foreground=fg_color,
            insertcolor=fg_color
        )
        
        # Настройка Combobox
        style.configure(
            "TCombobox",
            background=button_bg,
            foreground=fg_color,
            fieldbackground=button_bg,
            arrowcolor=fg_color
        )
        
        # Настройка меню
        style.configure(
            "TMenubutton",
            background=button_bg,
            foreground=fg_color
        )
    
    def schedule_update(self):
        self.update_profiles()
        self.root.after(1000, self.schedule_update)
    
    def on_root_click(self, event):
        # Если клик не по дереву и не по кнопкам в меню, скрываем меню
        if event.widget != self.tree and not isinstance(event.widget, ttk.Button):
            self.hide_actions()
    
    def on_tree_click(self, event):
        # Получаем элемент, по которому кликнули
        item = self.tree.identify_row(event.y)
        if not item:
            self.hide_actions()
            return
            
        # Получаем данные профиля
        values = self.tree.item(item)['values']
        if not values or len(values) < 2:
            self.hide_actions()
            return
            
        # Получаем имя профиля из первого столбца
        profile_name = str(values[0])  # Преобразуем в строку на всякий случай
        status = values[1]
        
        # Показываем меню действий
        self.show_actions_menu(event, profile_name, status)
    
    def hide_actions(self, event=None):
        if self.current_actions_frame:
            self.current_actions_frame.place_forget()
            self.current_actions_frame = None
    
    def show_actions_menu(self, event, name, status):
        # Скрываем предыдущую панель если она есть
        self.hide_actions()
        
        # Создаем новую панель с кнопками
        actions_frame = ttk.Frame(self.tree)
        
        if status == "stopped":
            launch_btn = ttk.Button(
                actions_frame, 
                text="Launch",
                command=lambda n=name: self.button_action(self.launch_profile, n)
            )
            launch_btn.pack(fill=tk.X, pady=1)
        else:
            stop_btn = ttk.Button(
                actions_frame, 
                text="Stop",
                command=lambda n=name: self.button_action(self.stop_profile, n)
            )
            stop_btn.pack(fill=tk.X, pady=1)
        
        edit_profile_btn = ttk.Button(
            actions_frame, 
            text="Edit",
            command=lambda n=name: self.button_action(self.edit_profile, n)
        )
        edit_profile_btn.pack(fill=tk.X, pady=1)
        
        proxy_data_btn = ttk.Button(
            actions_frame,
            text="Proxy Data",
            command=lambda n=name: self.button_action(self.update_proxy_info, n)
        )
        proxy_data_btn.pack(fill=tk.X, pady=1)
        
        rotate_asocks_btn = ttk.Button(
            actions_frame,
            text="Rotate asocks",
            command=lambda n=name: self.button_action(self.rotate_asocks, n)
        )
        rotate_asocks_btn.pack(fill=tk.X, pady=1)
        
        delete_btn = ttk.Button(
            actions_frame, 
            text="Delete",
            command=lambda n=name: self.button_action(self.delete_profile, n)
        )
        delete_btn.pack(fill=tk.X, pady=1)
        
        # Показываем новую панель
        actions_frame.place(x=event.x, y=event.y)
        self.current_actions_frame = actions_frame
    
    def button_action(self, action_func, name):
        # Получаем имя профиля из фрейма
        if not self.current_actions_frame:
            return
            
        # Выполняем действие и скрываем меню
        action_func(name)
        self.hide_actions()
    
    def update_profiles(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for name in self.manager.get_profile_names():
            status = self.manager.get_profile_status(name)
            profile = self.manager.profiles[name]
            
            proxy_type = None
            proxy_str = None
            proxy_info = "No proxy"
            
            if profile.proxy:
                proxy_type = 'socks5' if profile.proxy.server.startswith('socks5') else 'http'
                server = profile.proxy.server.split('://')[1].lstrip('/')
                proxy_str = f"{server}:{profile.proxy.port}"
                if profile.proxy.username:
                    proxy_str += f":{profile.proxy.username}:{profile.proxy.password}"
                
                # Проверяем кэш
                cache_key = f"{proxy_type}://{proxy_str}"
                if cache_key in proxy_info_cache:
                    proxy_info = proxy_info_cache[cache_key]
                else:
                    proxy_info = "No data"
            else:
                proxy_info = "No proxy"
            
            item = self.tree.insert(
                "",
                tk.END,
                values=(name, status, proxy_info)
            )
    
    def create_profile(self):
        dialog = CreateProfileDialog(self)
        name, proxy_str = dialog.get_profile_data()
        if not name:
            return
            
        try:
            asyncio.run(self.manager.create_profile(name, proxy_str))
            self.update_profiles()
        except Exception as e:
            logger.exception(f"Error creating profile: {e}")
            messagebox.showerror("Error", str(e))
    
    def launch_profile(self, name: str):
        try:
            # Запускаем профиль асинхронно
            asyncio.run_coroutine_threadsafe(
                self.manager.launch_profile(name),
                self.loop
            )
            
            # Обновляем интерфейс
            self.update_profiles()
        except Exception as e:
            logger.exception(f"Error launching profile: {e}")
            messagebox.showerror("Error", str(e))
    
    def stop_profile(self, name: str):
        try:
            task = self.manager.running_tasks.get(name)
            if task:
                # Останавливаем профиль асинхронно
                task.cancel()
                asyncio.run_coroutine_threadsafe(
                    asyncio.gather(task, return_exceptions=True),
                    self.loop
                )
                
            self.update_profiles()
        except Exception as e:
            logger.exception(f"Error stopping profile: {e}")
            messagebox.showerror("Error", str(e))
    
    def edit_profile(self, name: str):
        dialog = CreateProfileDialog(self, name)
        new_name, proxy_str = dialog.get_profile_data()
        if not new_name:
            return
            
        try:
            # Сначала обновляем имя если оно изменилось
            if new_name != name:
                self.manager.update_profile_name(name, new_name)
                name = new_name  # Используем новое имя для обновления прокси
                
            # Обновляем прокси
            asyncio.run(self.manager.update_proxy(name, proxy_str))
            
            # Если профиль запущен, перезапускаем его
            if self.manager.is_profile_running(name):
                self.stop_profile(name)
                self.launch_profile(name)
                
            self.update_profiles()
        except Exception as e:
            logger.exception(f"Error updating profile: {e}")
            messagebox.showerror("Error", str(e))
    
    def delete_profile(self, name: str):
        if messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete profile '{name}'?"
        ):
            try:
                self.manager.delete_profile(name)
                self.update_profiles()
            except Exception as e:
                logger.exception(f"Error deleting profile: {e}")
                messagebox.showerror("Error", str(e))
    
    def update_proxy_info(self, name: str):
        """Обновляет информацию о прокси для профиля"""
        profile = self.manager.profiles[name]
        if profile.proxy:
            proxy_type = 'socks5' if profile.proxy.server.startswith('socks5') else 'http'
            server = profile.proxy.server.split('://')[1].lstrip('/')
            proxy_str = f"{server}:{profile.proxy.port}"
            if profile.proxy.username:
                proxy_str += f":{profile.proxy.username}:{profile.proxy.password}"
            
            # Очищаем кэш
            cache_key = f"{proxy_type}://{proxy_str}"
            if cache_key in proxy_info_cache:
                del proxy_info_cache[cache_key]
            
            # Делаем новую проверку
            get_proxy_info(proxy_type, proxy_str)
        
        # Обновляем отображение
        self.update_profiles()
    
    def rotate_asocks(self, name: str):
        """Ротация IP через ASocks API"""
        if not self.manager.asocks_settings:
            messagebox.showwarning("Error", "Please configure ASocks settings first")
            return
            
        profile = self.manager.profiles[name]
        if not profile.proxy:
            messagebox.showwarning("Error", "No proxy configured for this profile")
            return
            
        try:
            # Получаем данные прокси из профиля
            proxy_port = profile.proxy.port
            proxy_server = profile.proxy.server.split('://')[1].lstrip('/')
            
            logger.debug(f"Looking for proxy: {proxy_server}:{proxy_port}")
            
            # Формируем базовый URL
            base_url = self.manager.asocks_settings.domain.rstrip('/')
            api_key = self.manager.asocks_settings.api_key.strip()
            
            # Получаем список всех портов
            try:
                ports_url = f"{base_url}/v2/proxy/ports?apiKey={api_key}"
                logger.debug(f"Making request to {ports_url}")
                
                ports_response = requests.get(
                    ports_url,
                    timeout=10
                )
                
                logger.debug(f"Ports response status: {ports_response.status_code}")
                logger.debug(f"Ports response text: {ports_response.text}")
                
                if ports_response.status_code == 401:
                    messagebox.showerror("Error", "Invalid API key. Please check your settings.")
                    return
                elif ports_response.status_code != 200:
                    error_msg = ports_response.text if ports_response.text else "Failed to get ports list"
                    messagebox.showerror("Error", f"Failed to get ports: {error_msg}")
                    return
                    
                response_data = ports_response.json()
                if not response_data.get('success'):
                    messagebox.showerror("Error", "API request failed")
                    return
                    
                ports = response_data.get('message', {}).get('proxies', [])
                if not ports:
                    messagebox.showerror("Error", "No proxies found")
                    return
                
                logger.debug(f"Found {len(ports)} ports in ASocks")
                for port in ports:
                    logger.debug(f"Port data: {port}")
                    
            except requests.exceptions.RequestException as e:
                logger.exception(f"Network error getting ports: {e}")
                messagebox.showerror("Error", f"Network error: {str(e)}")
                return
            
            # Ищем нужный порт по IP и порту
            target_port = None
            for port in ports:
                port_proxy = port.get('proxy', '')
                port_id = port.get('id')
                port_login = port.get('login')
                port_password = port.get('password')
                
                logger.debug(f"Checking port {port_id}: proxy={port_proxy}, login={port_login}")
                
                if port_proxy:
                    proxy_parts = port_proxy.split(':')
                    if len(proxy_parts) == 2:
                        port_ip, port_port = proxy_parts
                        # Проверяем IP, порт и логин/пароль
                        if (port_ip == proxy_server and 
                            port_port == str(proxy_port) and
                            port_login == profile.proxy.username and
                            port_password == profile.proxy.password):
                            target_port = port
                            logger.debug(f"Found matching port: {port}")
                            break
                
            if not target_port:
                logger.error(f"Could not find port for {proxy_server}:{proxy_port} with login {profile.proxy.username}")
                messagebox.showerror("Error", "Proxy port not found in ASocks")
                return
            
            # Ротация IP
            try:
                rotate_url = f"{base_url}/v2/proxy/refresh/{target_port['id']}?apiKey={api_key}"
                logger.debug(f"Making request to {rotate_url}")
                
                response = requests.get(rotate_url, timeout=10)
                
                logger.debug(f"Rotate response status: {response.status_code}")
                logger.debug(f"Rotate response text: {response.text}")
                
                if response.status_code == 401:
                    messagebox.showerror("Error", "Invalid API key. Please check your settings.")
                    return
                elif response.status_code != 200:
                    error_msg = response.text if response.text else "Unknown error"
                    messagebox.showerror("Error", f"Failed to rotate IP: {error_msg}")
                    return
                    
                result = response.json()
                if result.get('success'):
                    # Очищаем кэш для этого прокси
                    proxy_type = 'socks5' if profile.proxy.server.startswith('socks5') else 'http'
                    server = profile.proxy.server.split('://')[1].lstrip('/')
                    proxy_str = f"{server}:{profile.proxy.port}"
                    if profile.proxy.username:
                        proxy_str += f":{profile.proxy.username}:{profile.proxy.password}"
                    cache_key = f"{proxy_type}://{proxy_str}"
                    if cache_key in proxy_info_cache:
                        del proxy_info_cache[cache_key]
                    
                    # Обновляем отображение и проверяем новый IP
                    self.update_profiles()
                    self.update_proxy_info(name)
                else:
                    error_msg = result.get('message', 'Unknown error')
                    messagebox.showerror("Error", f"Failed to rotate IP: {error_msg}")
                
            except requests.exceptions.RequestException as e:
                logger.exception(f"Network error during rotation: {e}")
                messagebox.showerror("Error", f"Network error during rotation: {str(e)}")
            
        except Exception as e:
            logger.exception(f"Error rotating IP: {e}")
            messagebox.showerror("Error", str(e))
    
    def show_settings(self):
        dialog = SettingsDialog(self)
        api_key, domain = dialog.get_settings()
        if api_key:
            self.manager.asocks_settings = ASocksSettings(api_key=api_key, domain=domain)
            self.manager.save_profiles()
    
    def run(self):
        # Запускаем event loop в отдельном потоке
        def run_loop():
            self.loop.run_forever()
            
        import threading
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        
        # Запускаем GUI
        self.root.mainloop()


def main():
    window = MainWindow()
    window.run() 