# Lidly v2

Een statisch, privacyvriendelijk dashboard voor actuele Lidl Nederland-aanbiedingen,
prijsmetingen, een boodschappenlijst en lokale calorietracking.

## Betrouwbare dealdata

`scraper.py` zoekt niet meer via `/q/search` en scant geen willekeurige eurobedragen.
De collector:

1. ontdekt de huidige week- en Weekenddeals-folders op het officiële Lidl-folderoverzicht;
2. haalt de gekoppelde gestructureerde data op via de openbare Lidl/Schwarz leaflet API;
3. accepteert alleen producten met een naam, numerieke prijs, HTTPS-afbeelding en Lidl-product-URL;
4. gebruikt de geldigheidsperiode van de officiële folder;
5. laat `old_price` en `discount` leeg wanneer Lidl die niet gestructureerd aanlevert.

Hierdoor kan een lege dealweergave correct zijn: onvolledige of niet-gestructureerde
folderitems worden bewust niet geraden.

## Lokaal draaien

Python 3.10+ is voldoende; er zijn geen externe Python-pakketten nodig.

```bash
python scraper.py
python -m http.server 8000 --directory public
```

Open daarna `http://localhost:8000`.

## Testen

```bash
python -m unittest discover -s tests -v
python -m py_compile scraper.py tests/test_scraper.py
```

## Dagelijkse refresh

`.github/workflows/refresh-deals.yml` draait dagelijks om 05:17 UTC en kan ook
handmatig worden gestart. De workflow test eerst de parser, vernieuwt `data.json`
en `price_history.json`, en commit alleen wanneer de snapshots veranderen.

GitHub Actions moet voor de repository schrijfrechten hebben via
**Settings → Actions → General → Workflow permissions → Read and write permissions**.

## Deployen

De inhoud van `public/` is volledig statisch en kan rechtstreeks naar GitHub Pages,
Netlify, Cloudflare Pages of een vergelijkbare host. Stel de publish directory in op
`public`. Voor GitHub Pages kan een aparte Pages workflow of branch-configuratie
worden gebruikt; de dagelijkse dataworkflow staat daar los van.

Calorieën en de gekozen winkel worden uitsluitend in browser-`localStorage`
opgeslagen. Er is geen backend en deze gegevens verlaten het apparaat niet.
