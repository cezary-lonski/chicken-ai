# Chicken AI (beta)

Kurczakowy asystent AI w oknie (Windows). Działa na Gemini, Claude albo OpenAI, do wyboru w Ustawieniach.

## Czym Chicken AI różni się od zwykłego czatu AI

| Funkcja | Chicken AI | Zwykły czat AI |
|---|---|---|
| Wygląd | Kurczakowy | Uniwersalny |
| Osobowość | Zabawna, kurczakowa; wiele kurczaków do wyboru | Uniwersalna |
| Tryb gracza | Specjalne narzędzia gamingowe | Ogólny asystent |
| Kurnik | Własne centrum narzędzi | Brak |
| Historia | Własne archiwum rozmów z wyszukiwarką | Historia czatów |
| Poziomy | XP i odblokowywanie funkcji | Brak |
| Mini gra | Kurczak Łucznik w czasie rysowania obrazka | Brak |

## Funkcje
- **Dostawcy AI:** Gemini, Claude (Anthropic), OpenAI. Własny klucz API, zapisywany tylko lokalnie.
- **Osobowości kurczaków:** Klasyk, Gamer, Koder, Mędrzec, Szef Kurnika, Własny (część odblokowuje się z poziomem).
- **Kurnik:** centrum narzędzi: generator pomysłów, kodu, obrazów oraz Tryb gracza (poradnik do gry, buildy i strategia, pomysł na grę, nazwy i lore).
- **System poziomów:** XP za rozmowy, obrazki, pracę agenta i strzelanie w mini grze; wyższe poziomy odblokowują osobowości i narzędzia.
- **Generowanie obrazków** (przycisk "Obraz" lub `/obraz opis`), zapis w `Obrazy\ChickenAI`. Gemini lub OpenAI.
- **Mini gra Kurczak Łucznik:** w czasie rysowania obrazka chodzisz strzałkami i strzelasz z łuku do potworów (spacja).
- **Tryb agenta:** czyta i zapisuje pliki oraz uruchamia komendy PowerShell w wybranym folderze. Zapis i komendy zawsze wymagają Twojej zgody.
- **Czat:** przycisk Zatrzymaj, odpowiedzi na żywo, zaznaczanie i kopiowanie wiadomości, możliwość pisania podczas myślenia (kolejka), historia z wyszukiwarką.
- **Logowanie przez Google** (opcjonalne): własny Client ID i Secret z Google Cloud Console (typ: Desktop app), wpisywane w Ustawieniach. Pokazuje Twoje imię i zdjęcie w aplikacji; tokeny nie są zapisywane.
- **Automatyczne aktualizacje** z GitHub Releases.

## Instalacja
Pobierz `ChickenAI-Setup.exe` z zakładki Releases i uruchom.
Przy pierwszym starcie wejdź w **Ustawienia** i wklej klucz API wybranego dostawcy:
Gemini (darmowy): https://aistudio.google.com/apikey, Claude: https://console.anthropic.com, OpenAI: https://platform.openai.com/api-keys.
Klucze, ustawienia i rozmowy zapisują się tylko lokalnie w `%APPDATA%\ChickenAI`.

## Budowanie ze źródeł
```
pip install -r requirements.txt
python chicken_ai.py
```
Instalator: zbuduj .exe PyInstallerem i skompiluj `installer.iss` w Inno Setup.

## Wydawanie aktualizacji
Zwiększ `VERSION` w `chicken_ai.py` i `AppVer` w `installer.iss`, zbuduj instalator i opublikuj release z tagiem `vX.Y.Z-beta` oraz plikiem `ChickenAI-Setup.exe`.
