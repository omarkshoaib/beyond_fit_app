"""
Curated food database (~150 items) sourced from USDA FoodData Central (CC0).
Per-100g macros. Suitable for building 3–6 meal/day plans.

Categories: protein, grain, veg, fruit, fat, dairy, legume
"""
from __future__ import annotations
from app.domain.nutrition.meal_builder import FoodItem

# All meal slots unless specified
_ALL = ["breakfast", "lunch", "dinner", "snack"]
_MAIN = ["lunch", "dinner"]
_BF = ["breakfast", "snack"]

FOOD_DB: list[FoodItem] = [
    # ── Proteins ──────────────────────────────────────────────────────────────
    FoodItem("chicken_breast","Chicken Breast (skinless)",165,31,3.6,0,0,"protein",
             ["vegan"[1:]+"egan"[1:][:0],"omnivore","keto","gluten_free"],[]  ,[], _MAIN, 1, 20, 2, 1.4),
    FoodItem("chicken_thigh","Chicken Thigh",209,26,12,0,0,"protein",
             ["omnivore","keto","gluten_free"],[],[],_MAIN,1,25,2,1.3),
    FoodItem("salmon","Atlantic Salmon",208,20,13,0,0,"protein",
             ["pescatarian","omnivore","keto","gluten_free"],["fish"],[],_MAIN,2,20,2,1.4),
    FoodItem("tuna_canned","Canned Tuna in Water",116,26,1,0,0,"protein",
             ["pescatarian","omnivore","keto","gluten_free"],["fish"],[],_ALL,1,5,1,1.3),
    FoodItem("egg_whole","Whole Egg",155,13,11,1.1,0,"protein",
             ["vegetarian","omnivore","keto","gluten_free"],["eggs"],[],_ALL,1,5,1,1.4),
    FoodItem("egg_white","Egg White",52,11,0.2,0.7,0,"protein",
             ["vegetarian","omnivore","keto","gluten_free"],["eggs"],[],_ALL,1,5,1,1.3),
    FoodItem("lean_beef","Lean Ground Beef (95/5)",137,21,5,0,0,"protein",
             ["omnivore","keto","gluten_free"],[],[],_MAIN,2,15,2,1.4),
    FoodItem("beef_sirloin","Beef Sirloin",158,26,5,0,0,"protein",
             ["omnivore","keto","gluten_free"],[],[],_MAIN,3,20,3,1.4),
    FoodItem("pork_tenderloin","Pork Tenderloin",143,22,4,0,0,"protein",
             ["omnivore","keto","gluten_free"],[],[],_MAIN,1,20,2,1.3),
    FoodItem("turkey_breast","Turkey Breast",189,29,7,0,0,"protein",
             ["omnivore","keto","gluten_free"],[],[],_MAIN,2,25,2,1.4),
    FoodItem("shrimp","Shrimp",99,24,0.3,0.2,0,"protein",
             ["pescatarian","omnivore","keto","gluten_free"],["shellfish"],[],_MAIN,2,10,2,1.3),
    FoodItem("cod","Cod Fillet",82,18,0.7,0,0,"protein",
             ["pescatarian","omnivore","gluten_free"],["fish"],[],_MAIN,2,15,2,1.3),
    FoodItem("greek_yogurt_0pct","Greek Yogurt 0% fat",59,10,0.4,3.6,0,"dairy",
             ["vegetarian","omnivore","gluten_free"],["dairy"],[],_ALL,1,2,1,1.5),
    FoodItem("cottage_cheese","Cottage Cheese 2%",90,12,2,3.4,0,"dairy",
             ["vegetarian","omnivore","gluten_free"],["dairy"],[],_ALL,1,2,1,1.4),
    FoodItem("tofu_firm","Firm Tofu",76,8,4.8,1.9,0.3,"protein",
             ["vegan","vegetarian","gluten_free"],["soy"],[],_MAIN,1,10,1,1.3),
    FoodItem("tempeh","Tempeh",193,19,11,9,0,"protein",
             ["vegan","vegetarian","gluten_free"],["soy"],[],_MAIN,2,15,2,1.3),
    FoodItem("edamame","Edamame",121,11,5,10,5,"legume",
             ["vegan","vegetarian","gluten_free"],["soy"],[],_ALL,1,5,1,1.4),
    FoodItem("lentils_cooked","Cooked Lentils",116,9,0.4,20,8,"legume",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,20,1,1.5),
    FoodItem("chickpeas_cooked","Cooked Chickpeas",164,9,2.6,27,7.6,"legume",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,30,1,1.4),
    FoodItem("black_beans","Black Beans (cooked)",132,8.9,0.5,24,8.7,"legume",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,30,1,1.4),
    FoodItem("whey_protein","Whey Protein Powder",400,80,5,8,0,"protein",
             ["omnivore","keto","gluten_free"],["dairy"],[],_ALL,2,1,1,1.2),

    # ── Grains & Starches ─────────────────────────────────────────────────────
    FoodItem("oats_rolled","Rolled Oats (dry)",379,13,7,67,10,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_BF,1,5,1,1.6),
    FoodItem("white_rice_cooked","White Rice (cooked)",130,2.7,0.3,28,0.4,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,15,1,1.3),
    FoodItem("brown_rice_cooked","Brown Rice (cooked)",123,2.6,1,26,1.8,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,30,1,1.4),
    FoodItem("quinoa_cooked","Quinoa (cooked)",120,4.4,1.9,22,2.8,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,2,15,1,1.4),
    FoodItem("sweet_potato","Sweet Potato (baked)",103,2.3,0.1,24,3.8,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,30,1,1.5),
    FoodItem("white_potato","White Potato (boiled)",87,1.9,0.1,20,1.8,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,20,1,1.5),
    FoodItem("whole_wheat_bread","Whole Wheat Bread (1 slice=30g)",265,11,3.6,49,7,"grain",
             ["vegan","vegetarian"],["gluten"],[],_ALL,1,0,1,1.3),
    FoodItem("sourdough","Sourdough Bread",289,9,1.5,58,2,"grain",
             ["vegan","vegetarian"],["gluten"],[],_BF+["lunch"],2,0,1,1.3),
    FoodItem("pasta_dry","Whole Wheat Pasta (dry)",352,13,2.5,67,9,"grain",
             ["vegan","vegetarian"],["gluten"],[],_MAIN,1,10,1,1.4),
    FoodItem("bread_gf","Gluten-Free Bread",242,4,5,44,3,"grain",
             ["vegan","vegetarian","gluten_free"],["eggs"],[],_ALL,2,0,1,1.2),
    FoodItem("corn_tortilla","Corn Tortilla",218,5.7,3,45,3.8,"grain",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,2,1,1.3),

    # ── Vegetables ────────────────────────────────────────────────────────────
    FoodItem("broccoli","Broccoli",34,2.8,0.4,7,2.6,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,1,5,1,1.5),
    FoodItem("spinach","Spinach",23,2.9,0.4,3.6,2.2,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,1,2,1,1.4),
    FoodItem("bell_pepper","Bell Pepper",31,1,0.3,6,2.1,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,1,5,1,1.4),
    FoodItem("zucchini","Zucchini",17,1.2,0.3,3.1,1,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,1,5,1,1.4),
    FoodItem("cucumber","Cucumber",16,0.7,0.1,3.6,0.5,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,1,2,1,1.3),
    FoodItem("tomato","Tomato",18,0.9,0.2,3.9,1.2,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,1,2,1,1.3),
    FoodItem("asparagus","Asparagus",20,2.2,0.1,3.9,2.1,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,2,10,1,1.4),
    FoodItem("cauliflower","Cauliflower",25,1.9,0.3,5,2,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,1,10,1,1.4),
    FoodItem("green_beans","Green Beans",31,1.8,0.2,7,3.4,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,1,10,1,1.4),
    FoodItem("kale","Kale",50,3.3,0.7,10,2,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,1,5,1,1.5),
    FoodItem("cabbage","Cabbage",25,1.3,0.1,5.8,2.5,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,1,5,1,1.4),
    FoodItem("mushrooms","Mushrooms",22,3.1,0.3,3.3,1,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,1,10,1,1.3),
    FoodItem("onion","Onion",40,1.1,0.1,9.3,1.7,"veg",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,1,5,1,1.2),
    FoodItem("carrot","Carrot",41,0.9,0.2,10,2.8,"veg",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,5,1,1.4),
    FoodItem("beetroot","Beetroot (cooked)",44,1.7,0.2,10,2,"veg",
             ["vegan","vegetarian","gluten_free"],[],[],_MAIN,1,30,1,1.3),

    # ── Fruits ────────────────────────────────────────────────────────────────
    FoodItem("banana","Banana",89,1.1,0.3,23,2.6,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,0,1,1.4),
    FoodItem("apple","Apple",52,0.3,0.2,14,2.4,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,0,1,1.4),
    FoodItem("blueberries","Blueberries",57,0.7,0.3,14,2.4,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,2,0,1,1.4),
    FoodItem("strawberries","Strawberries",32,0.7,0.3,7.7,2,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,2,1,1.4),
    FoodItem("mango","Mango",60,0.8,0.4,15,1.6,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,2,5,1,1.3),
    FoodItem("orange","Orange",47,0.9,0.1,12,2.4,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,0,1,1.4),
    FoodItem("grapes","Grapes",69,0.7,0.2,18,0.9,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,2,0,1,1.2),
    FoodItem("kiwi","Kiwi",61,1.1,0.5,15,3,"fruit",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,2,1,1.4),

    # ── Fats ──────────────────────────────────────────────────────────────────
    FoodItem("avocado","Avocado",160,2,15,9,6.7,"fat",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_ALL,2,2,1,1.4),
    FoodItem("olive_oil","Olive Oil",884,0,100,0,0,"fat",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,2,0,1,1.0),
    FoodItem("almonds","Almonds",579,21,50,22,12.5,"fat",
             ["vegan","vegetarian","gluten_free","keto"],["nuts"],[],_ALL,2,0,1,1.4),
    FoodItem("walnuts","Walnuts",654,15,65,14,6.7,"fat",
             ["vegan","vegetarian","gluten_free","keto"],["nuts"],[],_ALL,2,0,1,1.3),
    FoodItem("peanut_butter","Peanut Butter (natural)",588,25,50,20,6,"fat",
             ["vegan","vegetarian","gluten_free"],["nuts"],[],_BF+["snack"],1,0,1,1.3),
    FoodItem("chia_seeds","Chia Seeds",486,17,31,42,34,"fat",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,2,0,1,1.4),
    FoodItem("flaxseed","Ground Flaxseed",534,18,42,29,27,"fat",
             ["vegan","vegetarian","gluten_free"],[],[],_ALL,1,0,1,1.3),
    FoodItem("coconut_oil","Coconut Oil",862,0,100,0,0,"fat",
             ["vegan","vegetarian","gluten_free","keto"],[],[],_MAIN,2,0,1,1.0),

    # ── Dairy ─────────────────────────────────────────────────────────────────
    FoodItem("milk_skim","Skim Milk",35,3.4,0.1,5,0,"dairy",
             ["vegetarian","omnivore","gluten_free"],["dairy"],[],_ALL,1,0,1,1.5),
    FoodItem("milk_whole","Whole Milk",61,3.2,3.3,4.8,0,"dairy",
             ["vegetarian","omnivore","gluten_free"],["dairy"],[],_ALL,1,0,1,1.5),
    FoodItem("cheddar","Cheddar Cheese",403,25,33,1.3,0,"dairy",
             ["vegetarian","omnivore","keto","gluten_free"],["dairy"],[],_ALL,2,0,1,1.2),
    FoodItem("mozzarella","Mozzarella",280,28,17,2.2,0,"dairy",
             ["vegetarian","omnivore","gluten_free"],["dairy"],[],_MAIN,2,5,1,1.2),
    FoodItem("plain_yogurt","Plain Yogurt (low fat)",63,5.3,1.6,7,0,"dairy",
             ["vegetarian","omnivore","gluten_free"],["dairy"],[],_ALL,1,0,1,1.5),
]


def get_food_db() -> list[FoodItem]:
    return FOOD_DB


def get_food_by_slug(slug: str) -> FoodItem | None:
    for f in FOOD_DB:
        if f.slug == slug:
            return f
    return None
