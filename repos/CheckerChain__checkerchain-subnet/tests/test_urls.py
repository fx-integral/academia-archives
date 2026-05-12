from checkerchain.utils.checker_chain import fetch_product_data, fetch_products

if __name__ == "__main__":
    products = fetch_products()
    product = fetch_product_data("67cb23ec040c09b84a27db01")
    print(products)
    print(product)
