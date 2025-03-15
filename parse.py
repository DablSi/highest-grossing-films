import requests
from bs4 import BeautifulSoup
import re
import time
from pymongo import MongoClient

def clean_text(text):
    """Remove citation markers like [2] and extra whitespace."""
    text = re.sub(r'\[\d+\]', '', text)
    return " ".join(text.split())

def remove_sup_tags(tag):
    """Remove all <sup> tags from a BeautifulSoup tag."""
    for sup in tag.find_all('sup'):
        sup.decompose()
    return tag

def fix_glued_names(text):
    """
    Insert a space between a lowercase and an uppercase letter,
    which helps separate names that are accidentally glued.
    """
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

def extract_first_value_from_cell(td):
    """
    Iterate through the direct children of a <td> element, 
    ignoring <style> and <script> tags, and return the text from the first nonempty node.
    """
    td = remove_sup_tags(td)
    for child in td.children:
        # Skip tags that are style or script.
        if hasattr(child, 'name') and child.name in ['style', 'script']:
            continue
        if isinstance(child, str):
            text = child.strip()
            if text:
                return clean_text(text)
        else:
            text = child.get_text(" ", strip=True)
            if text:
                return clean_text(text)
    return clean_text(td.get_text(" ", strip=True))

def extract_director(td):
    """Extract only the first director from the 'Directed by' cell."""
    td = remove_sup_tags(td)
    a_tag = td.find("a")
    if a_tag:
        return fix_glued_names(clean_text(a_tag.get_text(strip=True)))
    value = extract_first_value_from_cell(td)
    return fix_glued_names(value)

def extract_country(td):
    """Extract only the first country from the cell."""
    td = remove_sup_tags(td)
    a_tag = td.find("a")
    if a_tag:
        return fix_glued_names(clean_text(a_tag.get_text(strip=True)))
    value = extract_first_value_from_cell(td)
    return fix_glued_names(value)

def extract_release_year(td):
    """Extract the first 4-digit year from the release date cell."""
    td = remove_sup_tags(td)
    text = clean_text(td.get_text(" ", strip=True))
    parts = re.split(r'[\n;]', text)
    if parts:
        match = re.search(r'\b(1[89]\d{2}|20\d{2})\b', parts[0])
        if match:
            return int(match.group(0))
    return None

def extract_box_office(td):
    """
    Extract the monetary amount along with its unit (billion/million) from the cell.
    Combines text nodes to ensure the unit isn't lost.
    """
    td = remove_sup_tags(td)
    combined_text = " ".join(list(td.stripped_strings))
    combined_text = combined_text.replace('\xa0', ' ')
    combined_text = clean_text(combined_text)
    amt_match = re.search(r'(\$[\d,\.]+)', combined_text)
    if amt_match:
        amount = amt_match.group(1)
        remaining = combined_text[amt_match.end():].lower()
        unit = ""
        if "billion" in remaining:
            unit = "billion"
        elif "million" in remaining:
            unit = "million"
        return f"{amount} {unit}".strip()
    parts = re.split(r'[\|\n]', combined_text)
    return parts[0].strip() if parts else combined_text

def get_film_info(film_url):
    """
    Given a film's Wikipedia URL, extract:
      - 'Directed by': first director only
      - 'Release date(s)': first release date's year
      - 'Country': first country value only
      - 'Box office': monetary value (with unit)
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(film_url, headers=headers)
    film_soup = BeautifulSoup(response.content, 'html.parser')
    info = {
        "director": None,
        "release_year": None,
        "country": None,
        "box_office": None
    }
    
    # Locate the infobox 
    infobox = film_soup.find("table", class_=lambda c: c and "infobox" in c)
    if not infobox:
        return info

    rows = infobox.find_all("tr")
    for row in rows:
        header = row.find("th")
        if not header:
            continue
        header_text = header.get_text(strip=True).lower()
        data_cell = row.find("td")
        if not data_cell:
            continue

        if "directed by" in header_text:
            info["director"] = extract_director(data_cell)
        elif "release date" in header_text:
            info["release_year"] = extract_release_year(data_cell)
        elif header_text in ["country", "countries", "country of origin"]:
            info["country"] = extract_country(data_cell)
        elif "box office" in header_text:
            info["box_office"] = extract_box_office(data_cell)
    return info

def extract_films():
    """
    Extract films from the main Wikipedia page on highest‑grossing films.
    For each film, extract the title (and link) from the main table,
    then follow that link to gather additional details.
    """
    url = "https://en.wikipedia.org/wiki/List_of_highest-grossing_films"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    films = []
    tables = soup.find_all("table", class_="wikitable")
    target_table = None
    for table in tables:
        caption = table.find("caption")
        if caption and "highest‑grossing films" in caption.get_text().lower():
            target_table = table
            break
    if target_table is None and tables:
        target_table = tables[0]
    
    header_row = target_table.find("tr")
    header_cells = header_row.find_all(["th", "td"])
    headers_list = [cell.get_text(strip=True).lower() for cell in header_cells]
    title_index = None
    for i, header in enumerate(headers_list):
        if "title" in header:
            title_index = i
            break

    rows = target_table.find_all("tr")[1:]
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells or len(cells) <= title_index:
            continue
        
        film_data = {}
        title_cell = cells[title_index]
        film_title = None
        film_link = None
        i_tag = title_cell.find("i")
        if i_tag:
            a_tag = i_tag.find("a")
            if a_tag:
                film_title = clean_text(a_tag.get_text(strip=True))
                film_link = a_tag.get("href")
            else:
                film_title = clean_text(i_tag.get_text(strip=True))
        else:
            a_tag = title_cell.find("a")
            if a_tag:
                film_title = clean_text(a_tag.get_text(strip=True))
                film_link = a_tag.get("href")
            else:
                film_title = clean_text(title_cell.get_text(strip=True))
        film_data["title"] = film_title
        film_data["director"] = None
        film_data["release_year"] = None
        film_data["country"] = None
        film_data["box_office"] = None

        if film_link:
            full_link = film_link if film_link.startswith("http") else "https://en.wikipedia.org" + film_link
            try:
                extra_info = get_film_info(full_link)
                film_data["director"] = extra_info.get("director")
                film_data["release_year"] = extra_info.get("release_year")
                film_data["country"] = extra_info.get("country")
                film_data["box_office"] = extra_info.get("box_office")
                time.sleep(1)  # Pause between requests.
            except Exception as e:
                print(f"Error fetching details for {film_title}: {e}")
        films.append(film_data)
    
    return films

if __name__ == "__main__":
    uri = "mongodb://admin:admin@localhost:27017/"
    
    client = MongoClient(uri)
    db = client["movies_database"]
    collection = db["highest_grossing_films"]

    # Clear existing documents
    collection.delete_many({})

    films_list = extract_films()

    result = collection.insert_many(films_list)
    print(f"Inserted {len(result.inserted_ids)} documents into MongoDB.")

    # For demonstration, print out the saved documents
    for film in collection.find():
        print(film)