import asyncio
import pickle
from asyncio import Task
from pathlib import Path
from typing import Union, List, Dict, Optional

from browserforge.fingerprints import FingerprintGenerator
from browserforge.headers import Browser
from browserforge.injectors.utils import InjectFunction, only_injectable_headers
from loguru import logger
from playwright.async_api import Page, async_playwright

from profile_manager.path import StealthPlaywrightPatcher
from profile_manager.structures import Profile, Proxy, ASocksSettings

USER_DATA_PATH = Path(__file__).parent.parent / 'user_data'

PROFILES_PATH = USER_DATA_PATH / 'profiles.pkl'
PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

EXTENSIONS_PATH = Path(__file__).parent.parent / 'extensions'

StealthPlaywrightPatcher().apply_patches()

class ProfileManager:
    def __init__(self):
        self.profiles: dict[str, Profile] = {}
        self.running_tasks: dict[str, Task] = {}
        self.asocks_settings: Optional[ASocksSettings] = None

        self.load_profiles()

    def load_profiles(self):
        try:
            if PROFILES_PATH.exists():
                with open(PROFILES_PATH, 'rb') as f:
                    data = pickle.load(f)
                    if isinstance(data, tuple):
                        self.profiles, self.asocks_settings = data
                    else:
                        self.profiles = data
                        self.asocks_settings = None
        except Exception as e:
            logger.exception(f'Error loading profiles: {e}')

    def get_extensions_args(self) -> list[str]:
        extensions_patches: str = self.get_extensions_patches()
        if not extensions_patches:
            return []

        return [
            f"--disable-extensions-except={extensions_patches}",
            f"--load-extension={extensions_patches}",
        ]

    @staticmethod
    def get_extensions_patches() -> str:
        if not EXTENSIONS_PATH.exists():
            return ''

        extension_dirs = [
            str(extension_path.resolve())
            for extension_path in EXTENSIONS_PATH.iterdir()
            if extension_path.is_dir()
        ]

        return ','.join(extension_dirs)

    def save_profiles(self):
        try:
            with open(PROFILES_PATH, 'wb') as f:
                pickle.dump((self.profiles, self.asocks_settings), f)
        except Exception as e:
            logger.exception(f'Error saving profiles: {e}')

    @staticmethod
    def parse_proxy(proxy_str: Union[str, None]) -> Union[Proxy, None]:
        if not proxy_str:
            return None

        parts = proxy_str.split(':')
        if len(parts) not in [3, 5]:
            raise ValueError(
                'Invalid proxy format. Use protocol:host:port or protocol:host:port:user:pass\n'
                'Where protocol is http or socks5. Socks5 does not supports user auth!',
            )

        return Proxy(
            server=f'{parts[0]}://{parts[1]}',
            port=int(parts[2]),
            username=parts[3] if len(parts) > 3 else None,
            password=parts[4] if len(parts) > 4 else None
        )

    async def create_profile(self, name: str, proxy_str: Union[str, None] = None) -> str:
        if name in self.profiles:
            raise ValueError(f'Profile "{name}" already exists')

        proxy = self.parse_proxy(proxy_str) if proxy_str else None

        fingerprint = FingerprintGenerator(
            browser=[
                Browser(name='chrome', min_version=130, max_version=135),
            ],
            # os=('windows', 'macos'),
            os=('windows',),
            device='desktop',
            locale=('en-US',),
            http_version=2
        ).generate()

        self.profiles[name] = Profile(fingerprint=fingerprint, proxy=proxy)
        self.save_profiles()
        return name

    async def launch_profile(self, profile_name: str):
        if profile_name not in self.profiles:
            raise ValueError('Profile not found')

        if self.is_profile_running(profile_name):
            raise ValueError('Profile is already running')

        task = asyncio.create_task(self._run_browser(profile_name))
        self.running_tasks[profile_name] = task

    async def update_proxy(self, profile_name: str, proxy_str: Union[str, None]):
        if profile_name not in self.profiles:
            raise ValueError('Profile not found')

        new_proxy = self.parse_proxy(proxy_str) if proxy_str else None
        self.profiles[profile_name].proxy = new_proxy
        self.save_profiles()

    def is_profile_running(self, profile_name: str) -> bool:
        task = self.running_tasks.get(profile_name)
        return task and not task.done()

    @staticmethod
    async def close_page_with_delay(page: Page, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await page.close()
        except Exception as e:
            logger.exception(f'Error closing page: {e}')

    async def _run_browser(self, profile_name: str):
        try:
            profile = self.profiles[profile_name]
            async with async_playwright() as playwright:
                user_data_path = USER_DATA_PATH / profile_name

                proxy_config = None
                if profile.proxy:
                    proxy_config = {
                        'server': f'{profile.proxy.server}:{profile.proxy.port}',
                        'username': profile.proxy.username,
                        'password': profile.proxy.password
                    }

                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_path,
                    channel='chrome',
                    headless=False,
                    user_agent=profile.fingerprint.navigator.userAgent,
                    color_scheme='dark',
                    viewport={
                        'width': profile.fingerprint.screen.width,
                        'height': profile.fingerprint.screen.height
                    },
                    extra_http_headers=only_injectable_headers(headers={
                        'Accept-Language': profile.fingerprint.headers.get(
                            'Accept-Language',
                            'en-US,en;q=0.9'
                        ),
                        **profile.fingerprint.headers,
                    }, browser_name='chrome'),
                    proxy=proxy_config,
                    ignore_default_args=[
                        '--enable-automation',
                        '--no-sandbox',
                        '--disable-blink-features=AutomationControlled',
                    ],
                    args=self.get_extensions_args(),
                )

                await context.add_init_script(
                    InjectFunction(profile.fingerprint),
                )

                # Закрываем стартовую about:blank
                for page in context.pages:
                    if page.url == 'about:blank':
                        _ = asyncio.create_task(
                            self.close_page_with_delay(page, delay=0.25),
                        )

                # Открываем страницы
                for page_url in profile.page_urls or ['https://amiunique.org/fingerprint']:
                    page: Page = await context.new_page()
                    _ = asyncio.create_task(page.goto(page_url))

                try:
                    while True:
                        await asyncio.sleep(0.25)

                        pages = context.pages
                        if not pages:
                            break

                        self.profiles[profile_name].page_urls = [
                            page.url
                            for page in pages
                            if page.url != 'about:blank'
                        ]
                except Exception as e:
                    logger.error(f"Monitoring error: {e}")

        except Exception as e:
            logger.exception(f'Profile {profile_name} error: {e}')
        finally:
            _ = self.running_tasks.pop(profile_name, None)
            self.save_profiles()

    def get_profile_names(self) -> list[str]:
        return list(self.profiles.keys())

    def get_profile_status(self, profile_name: str) -> str:
        return 'running' if self.is_profile_running(profile_name) else 'stopped'

    def delete_profile(self, profile_name: str):
        """Удаляет профиль и его данные"""
        if profile_name not in self.profiles:
            raise ValueError('Profile not found')

        # Останавливаем профиль если запущен
        if self.is_profile_running(profile_name):
            task = self.running_tasks.get(profile_name)
            if task:
                task.cancel()
                asyncio.run(asyncio.gather(task, return_exceptions=True))

        # Удаляем профиль из словаря
        del self.profiles[profile_name]

        # Удаляем директорию с данными профиля
        user_data_path = USER_DATA_PATH / profile_name
        if user_data_path.exists():
            import shutil
            shutil.rmtree(user_data_path)

        # Сохраняем изменения
        self.save_profiles()

    def update_profile_name(self, old_name: str, new_name: str):
        """Обновляет имя профиля"""
        if old_name not in self.profiles:
            raise ValueError('Profile not found')
            
        if new_name in self.profiles:
            raise ValueError(f'Profile "{new_name}" already exists')
            
        # Останавливаем профиль если запущен
        if self.is_profile_running(old_name):
            task = self.running_tasks.get(old_name)
            if task:
                task.cancel()
                asyncio.run(asyncio.gather(task, return_exceptions=True))
                
        # Переименовываем директорию
        old_path = USER_DATA_PATH / old_name
        new_path = USER_DATA_PATH / new_name
        if old_path.exists():
            import shutil
            shutil.move(old_path, new_path)
            
        # Обновляем профиль в словаре
        self.profiles[new_name] = self.profiles.pop(old_name)
        
        # Сохраняем изменения
        self.save_profiles()
