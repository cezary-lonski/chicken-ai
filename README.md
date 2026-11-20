# Chicken AI (beta)

Okienkowy asystent AI w stylu kurczaka, napędzany przez Google Gemini (Windows).

## Funkcje
- Czat z odpowiedziami na żywo, animowana kręcąca się głowa kurczaka podczas myślenia
- **Tryb agenta**: Gemini może wypisywać i czytać pliki, zapisywać pliki oraz uruchamiać komendy PowerShell w wybranym folderze. Zapis i komendy zawsze wymagają Twojej zgody.
- **Generowanie obrazków** (przycisk "Obraz" lub komenda `/obraz opis`), zapis w ObrazyChickenAI
- Historia rozmów, ustawienia (model, kreatywność, osobowość)
- **Automatyczne aktualizacje** z GitHub Releases (instalator pobierany i uruchamiany po kliknięciu "Zaktualizuj")

## Instalacja
Pobierz `ChickenAI-Setup.exe` z zakładki Releases i uruchom.
Przy pierwszym starcie wejdź w **Ustawienia** i wklej klucz API Gemini (darmowy: https://aistudio.google.com/apikey).
Klucz i rozmowy zapisują się tylko lokalnie w `%APPDATA%\ChickenAI`.

## Budowanie ze źródeł
```
pip install -r requirements.txt
python chicken_ai.py
```
Instalator: zbuduj .exe PyInstallerem (patrz polecenie w historii projektu) i skompiluj `installer.iss` w Inno Setup.

## Wydawanie aktualizacji
Zwiększ `VERSION` w `chicken_ai.py` i `AppVer` w `installer.iss`, zbuduj instalator i opublikuj release z tagiem `vX.Y.Z-beta` oraz plikiem `ChickenAI-Setup.exe`.
