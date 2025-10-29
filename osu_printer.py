import asyncio
import websockets
import json
import logging
from libfptr10 import IFptr
import os
from pathlib import Path

# логи 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ккт ебучая
config_file = Path("atol_printer_config.json")
config = {}
try:
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f: config = json.load(f)
except Exception as e:
    logging.error(f"Не удалось загрузить файл конфига: {e}")

COM_PORT = config.get("com_port", "COM5")
BAUD_RATE = config.get("baud_rate", 115200)

# Отслеживание состояния
previous_game_state = -1 # начально состояние
# А вот тут пошли переменны, которые потом в чек пихаем
live_score = 0
live_pp = 0.0
live_artist = "Unknown Artist"
live_title = "Unknown Song"
live_difficulty = ""


# Цепляемся к кассе
def connect_to_kkt():
    try:
        logging.info(f"Цепляюсь к ККТ по порту {COM_PORT}...")
        driver_path_x86 = r"C:\Program Files (x86)\ATOL\Drivers10\KKT\bin\fptr10.dll"
        driver_path_x64 = r"C:\Program Files\ATOL\Drivers10\KKT\bin\fptr10.dll"
        driver_path = None
        if os.path.exists(driver_path_x86): driver_path = driver_path_x86
        elif os.path.exists(driver_path_x64): driver_path = driver_path_x64
        if not driver_path: raise RuntimeError("Драйвер fptr10.dll не найден.")
        fptr = IFptr(driver_path)
        settings = {IFptr.LIBFPTR_SETTING_MODEL: IFptr.LIBFPTR_MODEL_ATOL_AUTO, IFptr.LIBFPTR_SETTING_PORT: IFptr.LIBFPTR_PORT_COM, IFptr.LIBFPTR_SETTING_COM_FILE: COM_PORT, IFptr.LIBFPTR_SETTING_BAUDRATE: BAUD_RATE}
        fptr.setSettings(settings)
        fptr.open()
        if not fptr.isOpened(): raise ConnectionError(f"Не удалось подключиться к ККТ: {fptr.errorDescription()}")
        logging.info("Успешно подключено к ККТ.")
        return fptr
    except Exception as e:
        logging.error(f"Ошибка подключения к ККТ: {e}", exc_info=True)
        return None

# Основная функция печати
def print_osu_receipt(fptr, score, pp, artist, title, difficulty):
    if not fptr or not fptr.isOpened():
        logging.error("Невозможно напечатать чек: ККТ не подключено.")
        return
    try:
        pp_after_vat = pp * 0.80
        score_after_vat = int(score * 0.80)
        map_string = f"{artist} - {title}"
        difficulty_string = f"[{difficulty}]"

        # ШАбЛОН ЧЕКА!
        receipt_text = (
            f"{map_string}\n"
            f"{difficulty_string}\n\n"
            f"-- osu! Play Result --\n\n"
            f"       SCORE:\n"
            f" {score:,}\n\n"
            f" PERFORMANCE POINTS (PP):\n"
            f" {pp:.2f}pp\n\n"
            f"--- Сумма ИТОГО ---\n"
            f"   (20% НДС)\n\n"
            f"       SCORE:\n"
            f" {score_after_vat:,}\n\n"
            f"       PP:\n"
            f" {pp_after_vat:.2f}pp\n\n"
            f"{'-' * 24}\n"
                        f" "
            f" Подписывайтесь на RUCAST!\n"
            f" t.me/osu_rucast\n"
            f"{'-' * 24}\n"
            f" "
            f"    Good game!"
        )
        
        logging.info("ПЕЧАТАЮ ТВОЙ СКОР, ПЕЧАТАЮ...")
        fptr.beginNonfiscalDocument()
        fptr.setParam(IFptr.LIBFPTR_PARAM_TEXT, receipt_text)
        fptr.setParam(IFptr.LIBFPTR_PARAM_ALIGNMENT, IFptr.LIBFPTR_ALIGNMENT_CENTER)
        fptr.setParam(IFptr.LIBFPTR_PARAM_TEXT_WRAP, IFptr.LIBFPTR_TW_WORDS) # Перенос строк, если слишком много букв вышло...
        result = fptr.printText()
        fptr.cut()
        fptr.endNonfiscalDocument()
        if result != 0: logging.error(f"Ошибка печати ({result}): {fptr.errorDescription()}")
        else: logging.info("Чек с результатами успешно напечатан.")
    except Exception as e:
        logging.error(f"Критическая ошибка при печати: {e}", exc_info=True)

async def tosu_listener(fptr):
    global previous_game_state, live_score, live_pp, live_artist, live_title, live_difficulty
    
    uri = "ws://127.0.0.1:24050/ws" # стандартный порт tosu
    
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                logging.info(f"Подключился к tosu! {uri}")

                # Подписка на поля
                subscribe_message = json.dumps({
                    "code": 0,
                    "value": [
                        "menu.state", "score", "pp.current",
                        "menu.bm.metadata.artist", "menu.bm.metadata.title",
                        "menu.bm.metadata.difficulty"
                    ]
                })
                await websocket.send(subscribe_message)
                logging.info("Отправлена подписка на данные игры и карты.")
                logging.info("Ожидание данных от игры")

                async for message in websocket:
                    data = json.loads(message)
                    
                    menu = data.get("menu", {})
                    gameplay = data.get("gameplay", {})
                    
                    if not menu or not gameplay:
                        continue

                    # Эта отладка СРЁТ НЕ ПО ДЕТСКИ. Если мешает или тебе страшно - можешь закомментировать или выпилить.
                    logging.info(f"Получены данные: menu.state={menu.get('state')}, gameplay.score={gameplay.get('score')}")

                    # Сохраняем данные о карте, когда они приходят
                    bm = menu.get("bm", {})
                    metadata = bm.get("metadata", {})
                    live_artist = metadata.get("artist", live_artist)
                    live_title = metadata.get("title", live_title)
                    live_difficulty = metadata.get("difficulty", live_difficulty)

                    game_state = menu.get("state")
                    
                    live_score = gameplay.get("score", live_score)
                    pp_data = gameplay.get("pp", {})
                    live_pp = pp_data.get("current", live_pp)

                    if game_state is not None:
                        if game_state != previous_game_state:
                            logging.info(f"Статус игры изменился: {previous_game_state} -> {game_state}")

                            if game_state == 7 and previous_game_state == 2:
                                logging.info("КАРТА ЗАВЕРШЕНА! Готовлю чек...")
                                # Передаем данные на печать, ура
                                print_osu_receipt(fptr, live_score, live_pp, live_artist, live_title, live_difficulty)
                            
                            previous_game_state = game_state
        
        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError) as e:
            logging.warning(f"Соединение потеряно: {e}. Переподключение через 10 секунд...")
            await asyncio.sleep(10)
        except Exception as e:
            logging.error(f"Произошла ошибка: {e}", exc_info=True)
            await asyncio.sleep(10)

if __name__ == "__main__":
    print("=======================================")
    print("      KKT osu! Bridge is running")
    print("      Удачи пофлексить своими чеками")
    print("=======================================")
    
    kkt_driver = connect_to_kkt()
    
    if kkt_driver:
        try:
            asyncio.run(tosu_listener(kkt_driver))
        finally:
            logging.info("Закрытие соединения с ККТ...")
            kkt_driver.close()
    else:
        print("\nНе удалось подключиться к ККТ. Программа будет завершена.")