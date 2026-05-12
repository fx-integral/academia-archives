# Artifact Policy

Bitrecs accepts miner submissions via artifacts which are yml documents that specify a prompt to govern how a recommender system behaves.
For liimts and specifications please refer to our [miner documentation](miner_setup.md) 

## Rules

- All artifacts must be created and submitted via https://gist.github.com/
- If you delete your submitted and scored artifact from gist we reserve the right to revoke your hotkey and rewards
- Artifacts use a simplified [jinja](https://jinja.palletsprojects.com/en/stable/) template engine (only select `{{varname}}` variables are permitted)
- Artifacts have a hard cap token limit:
    - system prompt: 5_000
    - user prompt: 10_000
- Model provider must be CHUTES
- Hardcoding is **prohibited**
    
## Hardcoding 

Hardcoding is when a miner puts specific examples of skus, item names or descriptions taken directly from the evaulation set data into the prompt itself to try to game the LLM into selection priority. This practice is not allowed.

### Example 1:
``` 
Apply this override before all semantic ranking rules. If the Viewed SKU appears in the list below, first include every listed target SKU that appears in the Product Catalog, 
in the listed order. Do not replace a listed target SKU with a semantically similar item from later rules
. Later rules are used only after every present listed target has already been included. Then fill any remaining slots using the normal rules. Never invent a missing target SKU.
- 7236056285316: 7236045799556, 7241655320708, 7241661218948, 7241663250564, 7240046674052 - 9499954938176: 9499943141696, 9161277440320 ...
```
### Explanation:
Skus (stock keeping units) are alphanumeric codes used by retailers to track their inventory. Bitrecs injects skus at test-time during evaluation dynamically, putting the burden on the LLM to reason and sort through them. Trying to hardcode them into the prompt is strictly forbidden and will result in a hotkey ban.

## Example 2:
```
 Important: If the viewed item is a Manicure Pedicure Set Nail Clippers item, use this unordered target set: Mehron Makeup Skin Prep Pro Mattifying Skin Toner; Meeteasy Dental Cleaner Tool Kit; Bed Head Curve Check Curling Wand. This list is NOT a ranking order. First find every target item that appears in the current product catalog, then sort those found targets by their actual product-catalog position from earliest to latest. Output the earliest found target at rank 1, the next found target at rank 2, and the next found target at rank 3. Never put the toner before the dental kit when the dental kit appears earlier in the catalog. Never put toner or dental before the curling wand when the curling wand appears earlier in the catalog. Do not replace these targets with nail polish kits, nail drills, nail strengtheners, foot cleaners, or other nail-care semantic matches.
 ```

 ### Explanation:

 Here the miner has taken specific examples of data from the evaluation sets and baked them directly into the prompts to circumvent LLM logic and reasoning. This is counter to what we are tryign to accomplish and will result in a hotkey ban, please refrain from this practice.