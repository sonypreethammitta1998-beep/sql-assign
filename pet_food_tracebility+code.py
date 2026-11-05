import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# All packages are built into Python.
# The data describe fictional dry-food production.
# Recipes and laboratory grades are educational assumptions,
# not approved formulations or food-safety standards.

SEED = 42
OUTPUT = Path("pet_food_traceability.db")
random_source = random.Random(SEED)


def build_schema(db):
    """Create separate formulation, production and testing records."""
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript("""
    CREATE TABLE food_recipes (
        recipe_id INTEGER PRIMARY KEY,
        recipe_code TEXT NOT NULL UNIQUE,
        recipe_name TEXT NOT NULL,
        recipe_version INTEGER NOT NULL CHECK (recipe_version > 0),
        target_species TEXT NOT NULL
            CHECK (target_species IN ('Dog', 'Cat')),
        product_form TEXT NOT NULL CHECK (product_form = 'Dry food'),
        created_on TEXT NOT NULL
            CHECK (
                date(created_on, '+0 days') IS NOT NULL
                AND date(created_on, '+0 days') = created_on
            ),

        UNIQUE (recipe_name, recipe_version)
    );

    CREATE TABLE ingredients (
        ingredient_id INTEGER PRIMARY KEY,
        ingredient_code TEXT NOT NULL UNIQUE,
        ingredient_name TEXT NOT NULL UNIQUE,
        ingredient_category TEXT NOT NULL
            CHECK (ingredient_category IN
                ('Animal protein', 'Plant protein', 'Cereal',
                 'Fibre', 'Fat', 'Supplement')),
        protein_percent REAL NOT NULL
            CHECK (protein_percent BETWEEN 0 AND 100)
    );

    CREATE TABLE recipe_ingredients (
        recipe_id INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL,
        ingredient_quantity_g INTEGER NOT NULL
            CHECK (ingredient_quantity_g BETWEEN 1 AND 1000),

        PRIMARY KEY (recipe_id, ingredient_id),
        FOREIGN KEY (recipe_id) REFERENCES food_recipes(recipe_id),
        FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
    );

    CREATE TABLE production_lots (
        lot_id INTEGER PRIMARY KEY,
        lot_code TEXT NOT NULL UNIQUE,
        recipe_id INTEGER NOT NULL,
        production_date TEXT NOT NULL
            CHECK (
                date(production_date, '+0 days') IS NOT NULL
                AND date(production_date, '+0 days') = production_date
            ),
        processing_temperature_c REAL NOT NULL
            CHECK (processing_temperature_c BETWEEN 70 AND 130),
        lot_weight_kg REAL NOT NULL
            CHECK (lot_weight_kg BETWEEN 100 AND 3000),
        expiry_date TEXT NOT NULL
            CHECK (
                date(expiry_date, '+0 days') IS NOT NULL
                AND date(expiry_date, '+0 days') = expiry_date
                AND expiry_date > production_date
            ),
        production_notes TEXT
            CHECK (
                production_notes IS NULL
                OR length(trim(production_notes)) > 0
            ),

        FOREIGN KEY (recipe_id) REFERENCES food_recipes(recipe_id)
    );

    CREATE TABLE laboratory_tests (
        lot_id INTEGER NOT NULL,
        test_number INTEGER NOT NULL CHECK (test_number > 0),
        sample_code TEXT NOT NULL
            CHECK (length(trim(sample_code)) > 0),
        completed_on TEXT NOT NULL
            CHECK (
                date(completed_on, '+0 days') IS NOT NULL
                AND date(completed_on, '+0 days') = completed_on
            ),
        protein_percent REAL NOT NULL
            CHECK (protein_percent BETWEEN 0 AND 100),
        inspection_grade TEXT NOT NULL
            CHECK (inspection_grade IN
                ('Unsatisfactory', 'Acceptable', 'Good', 'Excellent')),
        test_method TEXT NOT NULL
            CHECK (test_method = 'Simulated protein mass fraction'),
        laboratory_comments TEXT
            CHECK (
                laboratory_comments IS NULL
                OR length(trim(laboratory_comments)) > 0
            ),

        PRIMARY KEY (lot_id, test_number),
        FOREIGN KEY (lot_id) REFERENCES production_lots(lot_id)
    );

    -- Test completion must fall between production and expiry.
    CREATE TRIGGER validate_test_insert
    BEFORE INSERT ON laboratory_tests
    BEGIN
        SELECT RAISE(ABORT, 'Test date outside lot lifetime')
        WHERE NOT EXISTS (
            SELECT 1
            FROM production_lots
            WHERE lot_id = NEW.lot_id
              AND NEW.completed_on >= production_date
              AND NEW.completed_on < expiry_date
        );
    END;

    CREATE TRIGGER validate_test_update
    BEFORE UPDATE ON laboratory_tests
    BEGIN
        SELECT RAISE(ABORT, 'Test date outside lot lifetime')
        WHERE NOT EXISTS (
            SELECT 1
            FROM production_lots
            WHERE lot_id = NEW.lot_id
              AND NEW.completed_on >= production_date
              AND NEW.completed_on < expiry_date
        );
    END;
    """)


def register_ingredients(db):
    """Use fictional ingredient specifications on an as-fed mass basis."""
    catalogue = [
        ("Chicken meal", "Animal protein", 62),
        ("Turkey meal", "Animal protein", 60),
        ("Salmon meal", "Animal protein", 58),
        ("Whitefish meal", "Animal protein", 64),
        ("Lamb meal", "Animal protein", 55),
        ("Duck meal", "Animal protein", 57),

        ("Pea protein", "Plant protein", 70),
        ("Soy protein", "Plant protein", 65),
        ("Potato protein", "Plant protein", 72),

        ("Rice flour", "Cereal", 7),
        ("Oat flour", "Cereal", 12),
        ("Maize flour", "Cereal", 9),
        ("Barley flour", "Cereal", 10),
        ("Wheat flour", "Cereal", 11),

        ("Beet pulp", "Fibre", 8),
        ("Cellulose fibre", "Fibre", 0),
        ("Pumpkin powder", "Fibre", 9),
        ("Chicory fibre", "Fibre", 2),

        ("Chicken fat", "Fat", 0),
        ("Salmon oil", "Fat", 0),
        ("Sunflower oil", "Fat", 0),

        ("Vitamin blend", "Supplement", 0),
        ("Mineral blend", "Supplement", 0),
        ("Combined nutrient blend", "Supplement", 0)
    ]

    records = []
    groups = {}
    specifications = {}

    for number, (name, category, protein) in enumerate(catalogue, 1):
        records.append((
            number, f"ING-{number:03d}", name, category, protein
        ))
        groups.setdefault(category, []).append(number)
        specifications[number] = protein

    db.executemany(
        "INSERT INTO ingredients VALUES (?, ?, ?, ?, ?)", records
    )
    return groups, specifications


def formulate_recipes(db, groups, specifications):
    """
    Record six ingredients per recipe on a 1,000 g input basis.
    Versions remain separate so historical lots retain their formulation.
    """
    recipe_rows = []
    composition_rows = []
    expected_protein = {}

    for recipe_id in range(1, 31):
        species = "Dog" if recipe_id <= 15 else "Cat"
        version = 1 + (recipe_id - 1) % 3
        family = (recipe_id - 1) // 3 + 1

        recipe_rows.append((
            recipe_id,
            f"REC-{recipe_id:03d}",
            f"Dry Blend Family {family:02d}",
            version,
            species,
            "Dry food",
            (date(2024, 1, 1) + timedelta(days=recipe_id * 5)).isoformat()
        ))

        selected = [
            random_source.choice(groups[category])
            for category in [
                "Animal protein", "Plant protein", "Cereal",
                "Fibre", "Fat", "Supplement"
            ]
        ]

        # Cat recipes receive a greater animal-protein proportion.
        animal_g = random_source.randint(
            350 if species == "Cat" else 250,
            450 if species == "Cat" else 350
        )
        plant_g = random_source.randint(60, 110)
        fibre_g = random_source.randint(30, 60)
        fat_g = random_source.randint(50, 90)
        supplement_g = random_source.randint(15, 25)

        # The cereal quantity is the remainder: totals are exactly 1,000 g.
        cereal_g = 1000 - (
            animal_g + plant_g + fibre_g + fat_g + supplement_g
        )

        quantities = [
            animal_g, plant_g, cereal_g,
            fibre_g, fat_g, supplement_g
        ]

        expected_protein[recipe_id] = sum(
            grams / 1000 * specifications[ingredient_id]
            for ingredient_id, grams in zip(selected, quantities)
        )

        composition_rows.extend(
            (recipe_id, ingredient_id, grams)
            for ingredient_id, grams in zip(selected, quantities)
        )

    db.executemany(
        "INSERT INTO food_recipes VALUES (?, ?, ?, ?, ?, ?, ?)",
        recipe_rows
    )
    db.executemany(
        "INSERT INTO recipe_ingredients VALUES (?, ?, ?)",
        composition_rows
    )
    return expected_protein


def assign_grade(result, target):
    """
    Fictional ordered grades based on absolute deviation in percentage points.
    These grades assess simulated protein consistency only.
    """
    deviation = abs(result - target)
    if deviation <= 0.5:
        return "Excellent"
    if deviation <= 1.0:
        return "Good"
    if deviation <= 2.0:
        return "Acceptable"
    return "Unsatisfactory"


def manufacture_and_test(db, expected_protein):
    """Create 250 lots, with six distinct laboratory samples per lot."""
    lots = []
    tests = []

    # Each recipe appears at least once; later usage varies.
    recipe_schedule = list(range(1, 31))
    recipe_schedule += random_source.choices(
        range(1, 31),
        weights=[random_source.uniform(0.5, 3) for _ in range(30)],
        k=220
    )
    random_source.shuffle(recipe_schedule)

    # Explicit missingness: 20/250 production notes = 8%.
    missing_lot_notes = set(random_source.sample(range(1, 251), 20))

    for lot_id, recipe_id in enumerate(recipe_schedule, 1):
        produced = date(2025, 1, 1) + timedelta(
            days=random_source.randrange(330)
        )
        expiry = produced + timedelta(days=365)

        # Mostly mid-sized production lots with some smaller/larger runs.
        weight = round(random_source.triangular(200, 2500, 900), 2)
        temperature = round(
            random_source.triangular(80, 120, 98), 1
        )

        notes = (
            None if lot_id in missing_lot_notes
            else "Dry-food batch; formulation version recorded"
        )

        lots.append((
            lot_id, f"LOT-2025-{lot_id:04d}", recipe_id,
            produced.isoformat(), temperature, weight,
            expiry.isoformat(), notes
        ))

        # Finished weight is recorded independently of the 1 kg recipe basis.
        # Protein assumes comparable input/output moisture for this exercise.
        # It is not a complete processing mass-balance model.
        batch_shift = random_source.gauss(0, 0.65)

        # A small proportion of batches have greater formulation variation.
        if random_source.random() < 0.06:
            batch_shift += random_source.choice([-1, 1]) * (
                random_source.uniform(1.8, 2.8)
            )

        for test_number in range(1, 7):
            target = expected_protein[recipe_id]
            result = round(
                max(0, min(100,
                    target + batch_shift + random_source.gauss(0, 0.35)
                )), 2
            )

            completed = produced + timedelta(
                days=random_source.randint(1, 5)
            )

            tests.append((
                lot_id,
                test_number,
                f"SMP-{lot_id:04d}-{test_number:02d}",
                completed.isoformat(),
                result,
                assign_grade(result, target),
                "Simulated protein mass fraction",
                "Protein result recorded on an as-fed basis"
            ))

    # Explicit missingness: 150/1,500 original laboratory comments.
    missing_comments = set(
        random_source.sample(range(len(tests)), 150)
    )
    for index in missing_comments:
        row = list(tests[index])
        row[7] = None
        tests[index] = tuple(row)

    # Copy 15 records from different lots, choosing nonmissing comments.
    # Duplicate = same lot, sample code, date, result, grade,
    # method and comments, excluding test_number.
    # These represent repeated entry, NOT additional samples.
    duplicates = []
    copied_lots = random_source.sample(range(1, 251), 15)

    for lot_id in copied_lots:
        candidates = [
            row for row in tests
            if row[0] == lot_id and row[7] is not None
        ]
        # If all comments for one lot are missing, copy a missing-comment row.
        if not candidates:
            candidates = [row for row in tests if row[0] == lot_id]

        original = random_source.choice(candidates)
        duplicates.append(
            (original[0], 7) + original[2:]
        )

    db.executemany(
        "INSERT INTO production_lots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        lots
    )
    db.executemany(
        "INSERT INTO laboratory_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        tests + duplicates
    )


def reject_invalid_record(db, label, statement, values):
    """Test a constraint, then discard the attempted validation record."""
    db.execute("SAVEPOINT trial")
    rejected = False
    try:
        db.execute(statement, values)
    except sqlite3.IntegrityError:
        rejected = True
    finally:
        db.execute("ROLLBACK TO trial")
        db.execute("RELEASE trial")

    assert rejected, f"Constraint test failed: {label}"
    print("Constraint passed:", label)


def audit_database(db):
    """Print submission evidence and check composition and traceability."""
    expected_rows = {
        "food_recipes": 30,
        "ingredients": 24,
        "recipe_ingredients": 180,
        "production_lots": 250,
        "laboratory_tests": 1515
    }

    print("DATABASE INVENTORY")
    for table, expected in expected_rows.items():
        actual = db.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        assert actual == expected

        print(f"\n{table}: {actual:,} rows")
        for column in db.execute(f"PRAGMA table_info({table})"):
            _, name, storage, required, default, pk_order = column
            print(
                f"  {name}: {storage}; required={bool(required)}; "
                f"primary-key position={pk_order}"
            )
        print(
            "  Foreign keys:",
            db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        )

    # All recipes must total exactly 1,000 g.
    assert db.execute("""
        SELECT COUNT(*) FROM (
            SELECT r.recipe_id
            FROM food_recipes r
            LEFT JOIN recipe_ingredients i USING(recipe_id)
            GROUP BY r.recipe_id
            HAVING COALESCE(SUM(i.ingredient_quantity_g), 0) <> 1000
        )
    """).fetchone()[0] == 0

    # Production cannot precede the recipe's creation.
    assert db.execute("""
        SELECT COUNT(*)
        FROM production_lots l
        JOIN food_recipes r USING(recipe_id)
        WHERE l.production_date < r.created_on
    """).fetchone()[0] == 0

    # Test completion dates must follow production and precede expiry.
    assert db.execute("""
        SELECT COUNT(*)
        FROM laboratory_tests t
        JOIN production_lots l USING(lot_id)
        WHERE t.completed_on < l.production_date
           OR t.completed_on >= l.expiry_date
    """).fetchone()[0] == 0

    # Every lot has six distinct physical samples, despite copied entries.
    assert db.execute("""
        SELECT COUNT(*) FROM (
            SELECT l.lot_id
            FROM production_lots l
            LEFT JOIN laboratory_tests t USING(lot_id)
            GROUP BY l.lot_id
            HAVING COUNT(DISTINCT t.sample_code) <> 6
        )
    """).fetchone()[0] == 0

    # Recalculate the grade from the stored recipe and result.
    targets = dict(db.execute("""
        SELECT ri.recipe_id,
               SUM(ri.ingredient_quantity_g * i.protein_percent) / 1000.0
        FROM recipe_ingredients ri
        JOIN ingredients i USING(ingredient_id)
        GROUP BY ri.recipe_id
    """))

    for recipe_id, result, grade in db.execute("""
        SELECT l.recipe_id, t.protein_percent, t.inspection_grade
        FROM laboratory_tests t
        JOIN production_lots l USING(lot_id)
    """):
        assert grade == assign_grade(result, targets[recipe_id])

    print("\nMISSING VALUES")
    for table, column in [
        ("production_lots", "production_notes"),
        ("laboratory_tests", "laboratory_comments")
    ]:
        total, missing = db.execute(
            f"SELECT COUNT(*), "
            f"SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END) "
            f"FROM {table}"
        ).fetchone()
        print(f"{table}.{column}: {missing}/{total} = {missing/total:.2%}")

        if table == "production_lots":
            assert missing == 20
        else:
            # Original 150 missing comments are retained.
            # A copied row can also have NULL if its entire lot lacked comments.
            assert 150 <= missing <= 165

    groups, copies = db.execute("""
        SELECT COUNT(*), COALESCE(SUM(n - 1), 0)
        FROM (
            SELECT COUNT(*) AS n
            FROM laboratory_tests
            GROUP BY lot_id, sample_code, completed_on,
                     protein_percent, inspection_grade,
                     test_method, laboratory_comments
            HAVING COUNT(*) > 1
        )
    """).fetchone()

    assert groups == 15 and copies == 15
    print("\nDUPLICATE BUSINESS RECORDS")
    print("Original laboratory records: 1,500")
    print("Duplicate groups:", groups)
    print(f"Additional copies: {copies}/1515 = {copies/1515:.2%}")

    print("\nGRADE DISTRIBUTION")
    for grade, count in db.execute("""
        SELECT inspection_grade, COUNT(*)
        FROM laboratory_tests
        GROUP BY inspection_grade
    """):
        print(f"{grade}: {count}")

    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    print("\nCONSTRAINT REJECTION TESTS")

    first_component = db.execute(
        "SELECT * FROM recipe_ingredients LIMIT 1"
    ).fetchone()
    reject_invalid_record(
        db, "Composite recipe-ingredient key",
        "INSERT INTO recipe_ingredients VALUES (?, ?, ?)",
        first_component
    )

    first_test = db.execute(
        "SELECT * FROM laboratory_tests LIMIT 1"
    ).fetchone()
    reject_invalid_record(
        db, "Composite laboratory-test key",
        "INSERT INTO laboratory_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        first_test
    )

    reject_invalid_record(
        db, "Foreign-key reference",
        "INSERT INTO recipe_ingredients VALUES (?, ?, ?)",
        (99999, 1, 100)
    )

    reject_invalid_record(
        db, "Positive ingredient quantity",
        "INSERT INTO recipe_ingredients VALUES (?, ?, ?)",
        (99999, 1, -10)
    )

    existing_name = db.execute(
        "SELECT ingredient_name FROM ingredients WHERE ingredient_id = 1"
    ).fetchone()[0]

    reject_invalid_record(
        db, "Unique ingredient name",
        "INSERT INTO ingredients VALUES (?, ?, ?, ?, ?)",
        (99999, "VALIDATION-1", existing_name, "Cereal", 10)
    )

    reject_invalid_record(
        db, "Required ingredient name",
        "INSERT INTO ingredients VALUES (?, ?, ?, ?, ?)",
        (99999, "VALIDATION-2", None, "Cereal", 10)
    )

    invalid_test = list(first_test)
    invalid_test[1] = 99
    invalid_test[3] = "2020-01-01"

    reject_invalid_record(
        db, "Test date linked to production lot",
        "INSERT INTO laboratory_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        invalid_test
    )

    print("\nRecipe totals: all 1,000 g")
    print("Production and test dates: consistent")
    print("Protein grades: consistent with documented thresholds")
    print("Integrity: ok")
    print("Foreign-key violations: none")


# Run the complete workflow.
if OUTPUT.exists():
    OUTPUT.unlink()  # Replace only this generated database.

with sqlite3.connect(OUTPUT) as database:
    build_schema(database)
    ingredient_groups, protein_specs = register_ingredients(database)
    recipe_targets = formulate_recipes(
        database, ingredient_groups, protein_specs
    )
    manufacture_and_test(database, recipe_targets)
    database.commit()
    audit_database(database)
    database.commit()

print(f"\nReady: {OUTPUT.resolve()}")
print(f"Size: {OUTPUT.stat().st_size:,} bytes")

# Download automatically when running in Google Colab.
try:
    from google.colab import files
except ImportError:
    print("The database is saved in your current working folder.")
else:
    files.download(str(OUTPUT))