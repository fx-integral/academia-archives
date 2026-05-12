import re
import json
import logging
from collections import Counter
from typing import Any, Dict, List
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

RE_PRODUCT_NAME = re.compile(r"[^A-Za-z0-9 |-]")
RE_REASON = re.compile(r"[^A-Za-z0-9 ]")
RE_MODEL_NAME = re.compile(r"[^A-Za-z0-9._/: +-]")

@dataclass
class Product:
    sku: str
    name: str
    price: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(',', ':'))
  
        
    @staticmethod
    def try_parse_context_strict(context: str) -> List["Product"]:
        """
        Strict converter expects a json array of products with sku/name/price fields

        """ 
        result: List[Product] = []        
        try:
            products_data = json.loads(context)

            for product in products_data:
                sku = product.get("sku")
                name = product.get("name")
                price = product.get("price", "0")
                if not (sku and name and price):
                    continue
                
                sku = str(sku)
                name = str(name)
                price = str(price)
                name = RE_PRODUCT_NAME.sub("", name).strip()
                if not name or not sku:
                    continue
                    
                result.append(Product(sku=sku, name=name, price=price))
        except Exception as e:
            logging.error(f"try_parse_context_strict Exception: {e}")
            return []
        
        #result.sort(key=operator.attrgetter('name'))
        #result = sorted(result, key=lambda x: (x.sku.lower(), x.name.lower()))
        return result

   
    @staticmethod
    def get_dupe_count(products: List["Product"]) -> int:       
        try:
            if not products or len(products) == 0:
                return 0
            
            sku_counts = Counter(
                product.sku if isinstance(product, Product) else product.get('sku')
                for product in products
            )
            return sum(count - 1 for count in sku_counts.values() if count > 1)
        except AttributeError as a:
            logging.error(f"WARNING - get_dupe_count failed: {a}")
            return -1
        except Exception as e:
            logging.error(f"ERROR - get_dupe_count encountered an unexpected error: {e}")
            return -1


    @staticmethod
    def extract_products_from_prompt(completion_request, exclude_last_n: int = 3) -> List["Product"]:
        """
        Extract and parse products from a ChatCompletionRequest prompt with smart filtering.
        
        Strategy:
        1. First try to find products within <context></context> tags (most reliable)
        2. If no context tags, use greedy matching but exclude the last N products
           (assuming they're example outputs, not catalog items)
    
        Args:
            completion_request: The chat completion request
            exclude_last_n: Number of products to exclude from the end (default 3)
    
        Returns:
            List of Product objects from the catalog (excludes example outputs)
        """
        try:
            # Concatenate all message contents
            full_prompt = " ".join([msg.get("content", "") for msg in completion_request.messages])
            
            # Strategy 1: Try to extract from <context> tags first
            context_pattern = r'<context>\s*(.*?)\s*</context>'
            context_matches = re.findall(context_pattern, full_prompt, re.DOTALL | re.IGNORECASE)
            
            if context_matches:
                # Found context tags - use the most reliable approach
                context_content = max(context_matches, key=len)
                json_array_pattern = r'\[(?:\s*\{[^}]*\}\s*,?\s*)+\]'
                matches = re.findall(json_array_pattern, context_content, re.DOTALL)
                
                if matches:
                    largest_match = max(matches, key=len)
                    unescaped = largest_match.replace('\\"', '"').replace("\\'", "'")
                    products = Product.try_parse_context_strict(unescaped)
                    logger.info(f"Extracted {len(products)} products from <context> tags")
                    return products
            
            # Strategy 2: No context tags - use greedy matching with trimming
            logger.info("No <context> tags found, using greedy matching with trimming")
            json_array_pattern = r'\[(?:\s*\{[^}]*\}\s*,?\s*)+\]'
            matches = re.findall(json_array_pattern, full_prompt, re.DOTALL)
            
            if not matches:
                logger.warning("No JSON array found in prompt")
                return []
            
            # Get the largest match (likely the catalog)
            largest_match = max(matches, key=len)
            unescaped = largest_match.replace('\\"', '"').replace("\\'", "'")
            
            # Parse all products
            all_products = Product.try_parse_context_strict(unescaped)
            
            # Handle exclusion logic
            if exclude_last_n == 0:
                # No exclusion - return all products
                logger.info(f"Extracted {len(all_products)} products (no exclusion)")
                return all_products
            
            if len(all_products) <= exclude_last_n:
                # If we have fewer products than the exclusion threshold,
                # it's likely just an example output, return empty
                logger.warning(f"Found only {len(all_products)} products, likely just example output")
                return []
            
            # Exclude the last N products (likely example outputs)
            catalog_products = all_products[:-exclude_last_n]
            logger.info(f"Extracted {len(catalog_products)} products (excluded last {exclude_last_n} as examples)")
            return catalog_products
            
        except Exception as e:
            logger.error(f"extract_products_from_prompt failed: {e}")
            return []


    @staticmethod
    def count_products_in_prompt(completion_request, exclude_last_n: int = 3) -> int:
        """
        Count the number of valid products in a prompt.
    
        Args:
            completion_request: The chat completion request
            exclude_last_n: Number of products to exclude from the end when no <context> tags (default 3)
    
        Returns:
            Number of catalog products (excludes example outputs)
        """
        products = Product.extract_products_from_prompt(completion_request, exclude_last_n)
        return len(products)
    
    @staticmethod
    def get_dupe_percentage(products: List["Product"]) -> float:
        """
        Calculate the percentage of duplicate SKU occurrences in the product list.
    
        Example: 187 products with 1 SKU duplicated once = 1 duplicate / 187 total = 0.53%
    
        Args:
            products: List of Product objects
    
        Returns:
            Percentage of products that are duplicates (0-100)
        """
        try:
            total_count = len(products)
            if total_count == 0:
                return 0.0
            
            dupe_count = Product.get_dupe_count(products)
            if dupe_count < 0:
                return 0.0
            
            # Percentage of the array that consists of duplicate entries
            dupe_percentage = (dupe_count / total_count) * 100
            return round(dupe_percentage, 2)  # Round to 2 decimals for readability
        
        except Exception as e:
            logger.error(f"get_dupe_percentage failed: {e}")
            return 0.0