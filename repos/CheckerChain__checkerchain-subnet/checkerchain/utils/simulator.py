import random, requests


def simulate_mining(num):
    # Simulate a trust score between 0 and 100
    trust_score = min(max(int(random.uniform(0, 100)), 0), 100)
    if trust_score < 20:
        trust_score = None
    return trust_score


def get_first_product():
    url = "https://backend.checkerchain.com/api/v1/products?page=1&limit=30"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        if "data" in data and "products" in data["data"]:
            products = data["data"]["products"]
            if products:
                return products[0]  # Return the first product
            else:
                return "No products found."
        else:
            return "Invalid data structure."
    else:
        return f"Error: {response.status_code}"
