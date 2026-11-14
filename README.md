# Ingen aning

Partyspel för ett rum fullt av folk. Alla utom en får samma ord på mobilen. Ni säger ett ord var som ledtråd, röstar på vem som inte hade en aning, och den ovetande försöker gissa ordet.

## Så spelar man

1. En startar ett rum och blir värd. Övriga går in med rumskoden eller QR-koden på TV:n.
2. Alla vänder sin lapp. En spelare får bara veta kategorin.
3. Appen slumpar vem som börjar. Ett ord var, medsols. Ett varv om ni är sex eller fler, annars två.
4. Värden trycker "Alla har sagt sitt". Alla som kan ordet röstar på vem som är ovetande. Den ovetande har en egen knapp att trycka på, så att ingen avslöjas av vad de gör med mobilen.
5. Den ovetande pekas ut och säger sin gissning högt. Alla som kunde ordet svarar ja eller nej i mobilen. Minst hälften ja räcker, så lika går till den som gissade. Blir juryn inte klar på 20 sekunder avgör värden (eller första jurymedlemmen, om värden själv är den ovetande).

Poäng: 1 för rätt röst. Den ovetande får 2 för rätt ord och 1 om färre än hälften pekade ut hen.

TV-vyn finns på `/tv`. Den visar rumskod, vilka som låst sin röst, vem som pekats ut och ställningen, men aldrig ordet förrän juryn har röstat.

## Köra lokalt

```
pip install -r requirements.txt pytest httpx
uvicorn app.main:app --reload
pytest
```

## Azure Web App

Linux-plan med Python 3.12 eller senare. Allt speltillstånd ligger i minnet, så appen måste köras som exakt en process:

- Startkommando: `gunicorn -w 1 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000`
- En instans, ingen utskalning
- Always On påslaget
- Web sockets påslaget
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` så att `requirements.txt` installeras vid deploy

En omstart eller ny deploy nollställer alla rum.

## Filer

- `app/game.py`: spelreglerna, utan nätverk
- `app/main.py`: rum, WebSocket och statiska filer
- `app/words.json`: kategorier och ord
- `static/`: spelarvyn (`index.html`, `player.js`) och TV-vyn (`tv.html`, `tv.js`)
- `static/qrcode.js`: qrcode-generator av Kazuhiko Arase, MIT-licens
