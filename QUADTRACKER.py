import requests
from bs4 import BeautifulSoup
import json
import os
import hashlib
from twilio.rest import Client

# Constants
QUADECA_MERCH_URL = "https://quadeca.com/collections/all"
QUADECA_TOUR_URL = "https://quadeca.com/pages/tour"
DATA_FILE = "last_known_state.json"
GITHUB_WORKSPACE = os.environ.get("GITHUB_WORKSPACE", ".")

# Twilio stuff - you'll set these as GitHub secrets
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
YOUR_PHONE_NUMBER = os.environ.get("YOUR_PHONE_NUMBER")


def get_page_content(url):

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def compute_hash(content):

    return hashlib.md5(content.encode()).hexdigest()


def extract_merch_info(html_content):

    soup = BeautifulSoup(html_content, 'html.parser')

    products = []

    product_elements = soup.find_all('div', class_='product-card')

    if not product_elements:
        product_elements = soup.find_all('div', class_='product-item')

    if not product_elements:
        for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'span', 'div']):
            if tag.text and "IDMTHY" in tag.text:
                parent = tag.parent
                if parent not in product_elements:
                    product_elements.append(parent)

    for product in product_elements:
        try:
            title_element = None
            for element in product.find_all(['h1', 'h2', 'h3', 'h4', 'span', 'div']):
                if element.text and "IDMTHY" in element.text:
                    title_element = element
                    break

            price_element = None
            for element in product.find_all(['span', 'div', 'p']):
                if element.text and "$" in element.text:
                    price_element = element
                    break

            sold_out = False
            for element in product.find_all(['span', 'div', 'button']):
                if element.text and "Sold out" in element.text:
                    sold_out = True
                    break

            url = ""
            link = product.find('a')
            if link and link.has_attr('href'):
                url = link['href']

                if url and not url.startswith('http'):
                    url = "https://quadeca.com" + url


            product_info = {
                'title': title_element.text.strip() if title_element else "Unknown Title",
                'price': price_element.text.strip() if price_element else "Unknown Price",
                'url': url,
                'sold_out': sold_out
            }

            products.append(product_info)
        except Exception as e:
            print(f"Error extracting product info: {e}")

    return products


def extract_tour_info(html_content):

    soup = BeautifulSoup(html_content, 'html.parser')

    tour_dates = []

    date_elements = []
    for element in soup.find_all(['div', 'li', 'section']):
        if element.has_attr('class'):
            class_str = ' '.join(element['class'])
            if 'tour' in class_str or 'event' in class_str:
                date_elements.append(element)

    if not date_elements:
        months = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December',
                  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        for element in soup.find_all(['div', 'p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5']):
            if element.text:
                for month in months:
                    if month in element.text:
                        date_elements.append(element)
                        break

    for date_element in date_elements:
        try:

            date_text = date_element.text.strip()

            location_text = "Unknown Location"
            venue_text = "Unknown Venue"

            if date_element.parent:
                siblings = list(date_element.parent.children)

                for i, sibling in enumerate(siblings):
                    if sibling == date_element:
                        if i + 1 < len(siblings):
                            next_sibling = siblings[i + 1]
                            if hasattr(next_sibling, 'text'):
                                location_text = next_sibling.text.strip()

                        if i + 2 < len(siblings):
                            next_next_sibling = siblings[i + 2]
                            if hasattr(next_next_sibling, 'text'):
                                venue_text = next_next_sibling.text.strip()

                        break

            tour_info = {
                'date': date_text,
                'location': location_text,
                'venue': venue_text
            }

            tour_dates.append(tour_info)
        except Exception as e:
            print(f"Error extracting tour info: {e}")

    return tour_dates


def load_last_known_state():
    file_path = os.path.join(GITHUB_WORKSPACE, DATA_FILE)

    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return json.load(f)
    else:
        return {
            'merch_hash': None,
            'tour_hash': None,
            'merch_items': [],
            'tour_dates': []
        }


def save_current_state(state):
    file_path = os.path.join(GITHUB_WORKSPACE, DATA_FILE)

    with open(file_path, 'w') as f:
        json.dump(state, f, indent=2)


def send_text_notification(message):

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, YOUR_PHONE_NUMBER]):
        print("Warning: Twilio credentials not configured. Would have sent this message:")
        print(message)
        return

    try:
        # Initialize the Twilio client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Send the message
        client.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=YOUR_PHONE_NUMBER
        )
        print(f"Successfully sent message: {message}")
    except Exception as e:
        print(f"Error sending text message: {e}")


def compare_and_notify(current_state, last_state):
    """Compare current and previous states and send notifications if needed."""
    notifications = []

    # Check if there are changes to merch
    if current_state['merch_hash'] != last_state['merch_hash']:
        # Get all product titles from current and previous states
        current_titles = set()
        for item in current_state['merch_items']:
            current_titles.add(item['title'])

        previous_titles = set()
        for item in last_state['merch_items']:
            previous_titles.add(item['title'])

        # Find new titles (in current but not in previous)
        new_titles = current_titles - previous_titles

        # Check for previously sold out items now in stock
        back_in_stock = []
        for current_item in current_state['merch_items']:
            for previous_item in last_state['merch_items']:
                if (current_item['title'] == previous_item['title'] and
                        previous_item.get('sold_out', True) and
                        not current_item.get('sold_out', True)):
                    back_in_stock.append(current_item['title'])

        # Create notifications
        if new_titles:
            notifications.append(f"New Quadeca merch found: {', '.join(new_titles)}")
        if back_in_stock:
            notifications.append(f"Items back in stock: {', '.join(back_in_stock)}")
        if not new_titles and not back_in_stock:
            notifications.append("Changes detected on Quadeca's merch page!")

    # Check if there are changes to tour info
    if current_state['tour_hash'] != last_state['tour_hash']:
        # Try to identify new tour dates
        if current_state['tour_dates'] and not last_state['tour_dates']:
            notifications.append(f"Quadeca tour dates found! {len(current_state['tour_dates'])} dates available.")
        elif len(current_state['tour_dates']) > len(last_state['tour_dates']):
            new_count = len(current_state['tour_dates']) - len(last_state['tour_dates'])
            notifications.append(f"{new_count} new Quadeca tour dates added!")
        else:
            notifications.append("Changes detected on Quadeca's tour page!")

    # Send notifications if we have any
    if notifications:
        message = "QUADECA UPDATE: " + " ".join(notifications) + " Check the website for details!"
        send_text_notification(message)
        return True  # Changes were detected

    return False  # No changes detected


def main():
    print("Starting Quadeca website check...")

    # Load the previously saved state
    last_known_state = load_last_known_state()

    # Get current merch info
    try:
        merch_content = get_page_content(QUADECA_MERCH_URL)
        merch_hash = compute_hash(merch_content)
        merch_items = extract_merch_info(merch_content)
    except Exception as e:
        print(f"Error checking merch page: {e}")
        # In case of error, use the previous state
        merch_hash = last_known_state['merch_hash']
        merch_items = last_known_state['merch_items']

    # Get current tour info
    try:
        tour_content = get_page_content(QUADECA_TOUR_URL)
        tour_hash = compute_hash(tour_content)
        tour_dates = extract_tour_info(tour_content)
    except Exception as e:
        print(f"Error checking tour page: {e}")
        # In case of error, use the previous state
        tour_hash = last_known_state['tour_hash']
        tour_dates = last_known_state['tour_dates']

    # Create current state object
    current_state = {
        'merch_hash': merch_hash,
        'tour_hash': tour_hash,
        'merch_items': merch_items,
        'tour_dates': tour_dates
    }

    # Skip notification on first run (when we have no previous state)
    if last_known_state['merch_hash'] is None:
        print("First run - saving initial state without sending notifications")
        save_current_state(current_state)
        return

    # Compare states and send notifications if needed
    changes_detected = compare_and_notify(current_state, last_known_state)

    if changes_detected:
        print("Changes detected! Notifications sent.")
    else:
        print("No changes detected.")

    # Save the current state for future comparisons
    save_current_state(current_state)

    print("Check completed successfully.")


# Run the main function when the script is executed
if __name__ == "__main__":
    main()