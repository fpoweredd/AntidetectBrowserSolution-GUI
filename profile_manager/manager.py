import asyncio
from asyncio import Task
import logging
from pathlib import Path
import pickle

from browserforge.fingerprints import FingerprintGenerator
from browserforge.headers import Browser
from browserforge.injectors.utils import InjectFunction
from patchright.async_api import Page, async_playwright

from profile_manager.structures import Profile, Proxy

logger = logging.getLogger(__name__)

PROFILES_PATH = Path('user_data/profiles.pkl')
PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

EXTENSIONS_PATH = Path('extensions')


class ProfileManager:
    def __init__(self):
        self.profiles: dict[str, Profile] = {}
        self.running_tasks: dict[str, Task] = {}

        self.load_profiles()

    def load_profiles(self):
        try:
            if PROFILES_PATH.exists():
                with open(PROFILES_PATH, 'rb') as f:
                    self.profiles = pickle.load(f)
        except Exception:
            logger.exception('Error loading profiles')

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
        extension_dirs = [
            str(extension_path.resolve())
            for extension_path in EXTENSIONS_PATH.iterdir()
            if extension_path.is_dir()
        ]

        return ','.join(extension_dirs)

    def save_profiles(self):
        with open(PROFILES_PATH, 'wb') as f:
            pickle.dump(self.profiles, f)

    @staticmethod
    def parse_proxy(proxy_str: str | None) -> Proxy | None:
        if not proxy_str:
            return None

        parts = proxy_str.split(':')
        if len(parts) not in [2, 4]:
            raise ValueError('Invalid proxy format. Use host:port or host:port:user:pass')

        return Proxy(
            server=parts[0],
            port=int(parts[1]),
            username=parts[2] if len(parts) > 2 else None,
            password=parts[3] if len(parts) > 3 else None
        )

    async def create_profile(self, name: str, proxy_str: str | None = None) -> str:
        if name in self.profiles:
            raise ValueError(f'Profile "{name}" already exists')

        proxy = self.parse_proxy(proxy_str) if proxy_str else None

        fingerprint = FingerprintGenerator(
            browser=[
                Browser(name='chrome', min_version=130, max_version=130),
            ],
            os=('windows', 'macos'),
            device='desktop',
            locale=('en-US',),
            http_version=2,
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

    async def update_proxy(self, profile_name: str, proxy_str: str | None):
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
        except Exception:
            pass

    async def _run_browser(self, profile_name: str):
        try:
            profile = self.profiles[profile_name]
            async with async_playwright() as playwright:
                user_data_path = f'user_data/{profile_name}'

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
                    extra_http_headers={
                        'Accept-Language': profile.fingerprint.headers.get(
                            'Accept-Language',
                            'en-US,en;q=0.9'
                        ),
                        **profile.fingerprint.headers
                    },
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
