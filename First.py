import asyncio
import random
from playwright.async_api import async_playwright
import pandas as pd
import re


PROFILE_PATH = "/Users/admin/Library/Application Support/Google/Chrome/Default"


# ====== Функции имитации человека ======
async def human_pause(min_s=0.8, max_s=2.5):
    """Случайная пауза (обдумывание)"""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_mouse_move(page, selector):
    """Движение мыши к элементу"""
    box = await page.locator(selector).bounding_box()
    if box:
        for _ in range(random.randint(2, 5)):
            x = box["x"] + random.uniform(0, box["width"])
            y = box["y"] + random.uniform(0, box["height"])
            await page.mouse.move(x, y, steps=random.randint(3, 10))


async def human_type_with_mistakes(page, selector, text, min_delay=0.1, max_delay=0.3):
    """Ввод текста с ошибками и исправлениями"""
    await page.click(selector)
    for char in text:
        # 5% шанс на ошибку
        if random.random() < 0.05:
            wrong_char = random.choice("abcdefghijklmnopqrstuvwxyz")
            await page.keyboard.type(wrong_char)
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.keyboard.press("Backspace")
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(min_delay, max_delay))


async def open_browser(p):
    return await p.chromium.launch_persistent_context(
        PROFILE_PATH,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized"
        ]
    )


async def warming_up(browser):
    warmup_page = await browser.new_page()
    await warmup_page.goto("https://news.google.com/")
    await human_pause(2, 4)
    await warmup_page.goto("https://www.youtube.com/")
    await human_pause(2, 4)
    await warmup_page.close()


async def hide_webdriver(page):
    # Скрытие webdriver
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)


async def search(page):
    await page.goto("https://www.google.com/")
    await page.wait_for_selector('textarea[name="q"], input[name="q"]')

    # Ввод запроса в Google
    await human_mouse_move(page, 'textarea[name="q"], input[name="q"]')
    await human_pause()
    part_number = input("Введите парт номер: ")
    await human_type_with_mistakes(page, 'textarea[name="q"], input[name="q"]', f"{part_number} Mouser")
    await human_pause()
    await page.keyboard.press("Enter")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector('a[href*="mouser.com"]')
    link = page.locator('a[href*="mouser.com"]').first
    href = await link.get_attribute("href")
    return href


async def get_stock(mouser_page):
    await mouser_page.wait_for_selector("h2.card-title.pdp-card-title")

    # Забираем текст
    stock_text = await mouser_page.locator("h2.card-title.pdp-card-title").inner_text()

    # Если нужно только число
    match = re.search(r"[\d.,]+", stock_text)
    if match:
        stock_value = match.group().replace(",", "")

    return stock_value


async def get_specs(mouser_page):
    # Ждём таблицу спецификаций
    await mouser_page.wait_for_selector("table.specs-table")

    # Извлекаем все строки
    rows = await mouser_page.locator("table.specs-table tr").all()

    specs = {}
    for row in rows:
        # Пропускаем header-строку, где th вместо td
        has_attr = await row.locator("td.attr-col").count()
        has_value = await row.locator("td.attr-value-col").count()
        if not (has_attr and has_value):
            continue

        # Извлекаем текст атрибута и значение
        attr_text = (await row.locator("td.attr-col").inner_text()).strip()
        val_text = (await row.locator("td.attr-value-col").inner_text()).strip()

        # Очищаем: убираем лишние двоеточия и whitespace
        attr = attr_text.rstrip(":").strip()
        value = val_text.strip()

        specs[attr] = value

    return specs


async def get_price(mouser_page):
    await mouser_page.wait_for_selector("table.pricing-table")

    # Находим все строки с ценами (у которых есть td с unit price)
    rows = await mouser_page.locator("table.pricing-table tr:has(td)").all()

    price_breaks = {}
    for row in rows:
        try:
            qty = await row.locator("th.pricebreak-col").inner_text()
            price = await row.locator("td.text-right").first.inner_text()

            # чистим лишнее
            qty = qty.strip()
            price = price.strip()

            price_breaks[qty] = price
        except:
            continue

    return price_breaks


async def get_lead_time(mouser_page):
    lead_time = await mouser_page.locator('div[aria-labelledby="factoryLeadTimeLabelHeader"]').inner_text()
    lead_time = lead_time.strip().split("\n")[0]  # берём только первую строку до иконки
    return lead_time  # 12 Weeks


async def get_description(mouser_page):
    # Ждём появления описания
    await mouser_page.wait_for_selector("#spnDescription")

    # Берём текст
    description = await mouser_page.locator("#spnDescription").inner_text()

    # Чистим пробелы и переводы строк
    description = description.strip()

    return description


columns = [
    "Stock Value",
    'Manufacturer', 'Product Category', 'RoHS', 'Packaging', 'Series', 'Resistance',
    'Power Rating', 'Tolerance', 'Temperature Coefficient', 'Minimum Operating Temperature',
    'Maximum Operating Temperature', 'Voltage Rating', 'Case Code - in', 'Case Code - mm',
    'Length', 'Width', 'Height', 'Application', 'Features', 'Brand', 'Mounting Style',
    'Product Type', 'Factory Pack Quantity', 'Subcategory', 'Technology', 'Termination Style',
    'Price_1pcs', 'Price_10pcs', 'Price_100pcs', 'Price_1000pcs', 'Price_2000pcs',
    'Price_5000pcs', 'Price_10000pcs', 'Price_50000pcs',
    'Lead Time',
    'Description'
]
df = pd.DataFrame(columns=columns)


async def main():
    async with async_playwright() as p:
        global df

        row_data = {}
        browser = await open_browser(p)

        # Прогрев
        await warming_up(browser)

        # Основная вкладка — Google
        page = await browser.new_page()

        # Скрытие webdriver
        await hide_webdriver(page)

        href = await search(page)

        mouser_page = await browser.new_page()
        await mouser_page.goto(href, timeout=60000, wait_until="domcontentloaded")
        await human_pause(2, 5)

        # Чтобы окно не закрылось сразу
        await human_pause(5, 10)

        stock = await get_stock(mouser_page)  #
        specs = await get_specs(mouser_page)  #
        price_breaks = await get_price(mouser_page)  #
        lead_time = await get_lead_time(mouser_page)  #
        description = await get_description(mouser_page)  #

        row_data = {
            "Stock Value": stock,
            **specs,  # распаковываем словарь характеристик
            **{f"Price_{k.replace('.', '')}pcs": v for k, v in price_breaks.items()},  # цены с нормализованными ключами
            "Lead Time": lead_time,
            "Description": description
        }

        # Добавляем строку в DataFrame
        df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
        print(df)


if __name__ == "__main__":
    asyncio.run(main())