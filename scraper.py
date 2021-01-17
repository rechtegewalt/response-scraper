import re
from typing import SupportsRound

import dataset
import get_retries
from bs4 import BeautifulSoup
from dateparser import parse

from hashlib import md5

from tqdm import tqdm

db = dataset.connect("sqlite:///data.sqlite")

tab_incidents = db["incidents"]
tab_sources = db["sources"]
tab_chronicles = db["chronicles"]


tab_chronicles.upsert(
    {
        "iso3166_1": "DE",
        "iso3166_2": "DE-HE",
        "chronicler_name": "response.",
        "chronicler_description": "response. ist die erste Beratungsstelle für Betroffene rechter Gewalt in Hessen und in der Bildungsstätte Anne Frank in Frankfurt angesiedelt.",
        "chronicler_url": "https://response-hessen.de/chronik",
        "chronicle_source": "https://response-hessen.de/chronik",
    },
    ["chronicler_name"],
)


BASE_URL = "https://response-hessen.de/chronik?page="


def fetch(url):
    html_content = get_retries.get(url, verbose=True, max_backoff=128).text
    soup = BeautifulSoup(html_content, "lxml")
    return soup


# https://stackoverflow.com/a/7160778/4028896
def is_url(s):
    regex = re.compile(
        r"^(?:http|ftp)s?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
        r"localhost|"  # localhost...
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return re.match(regex, s) is not None


def process_report(report, url, **kwargs):
    date = report.select_one("span.date-display-single").get_text().strip()
    date = parse(date, languages=["de"])

    rg_id = "response-" + report["class"][0]

    description = "\n".join(
        [x.get_text(separator="\n") for x in report.findChildren("p")]
    )
    city_title = report.select_one(".node__title.node-title").get_text().strip()

    if ":" in city_title:
        city, title = city_title.split(":")
        city = city.strip()
        title = title.strip()
    else:
        city, title = None, city_title

    source_list = report.select("div.field-name-field-source ul.item-list li")

    sources = []
    for s in source_list:
        s_item = {"name": s.get_text().replace("Quelle:", "").strip(), "rg_id": rg_id}
        a = s.select_one("a")
        if a is not None:
            s_item["url"] = a.get("href")
        sources.append(s_item)

    data = dict(
        chronicler_name="response.",
        title=title,
        description=description,
        city=city,
        date=date,
        rg_id=rg_id,
        url=url,
    )

    data = {**data, **kwargs}

    tab_incidents.upsert(data, ["rg_id"])

    for s in sources:
        tab_sources.upsert(s, ["rg_id", "name", "url"])


def process_page(page, url, **kwargs):
    for row in page.select("article.node-chronicle"):
        process_report(row, url, **kwargs)

    next_link = page.select_one("li.pager-next a")

    if next_link is None:
        return None

    return "https://response-hessen.de" + next_link.get("href")


soup = fetch(BASE_URL)
location_filters = [
    (x.get_text(), x.get("value"))
    for x in soup.select("#edit-field-district-tid option")
][1:]

motiv_filters = [
    (x.get_text(), x.get("value"))
    for x in soup.select("#edit-field-motivation-tid option")
][1:]

print(location_filters, motiv_filters)

next_link = BASE_URL
# 1. all
while True:
    next_link = process_page(soup, next_link)
    print(next_link)
    if next_link is None:
        break
    soup = fetch(next_link)

# 2. all counties
for label, l_id in location_filters:
    next_link = "https://response-hessen.de/chronik?field_district_tid=" + l_id
    while True:
        soup = fetch(next_link)
        next_link = process_page(soup, next_link, county=label)
        print(next_link)
        if next_link is None:
            break

# 3. all motives
for label, l_id in motiv_filters:
    next_link = "https://response-hessen.de/chronik?field_motivation_tid=" + l_id
    while True:
        soup = fetch(next_link)
        next_link = process_page(soup, next_link, motives=label)
        print(next_link)
        if next_link is None:
            break
