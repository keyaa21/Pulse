from flask import Flask, render_template, request, jsonify
from neo4j import GraphDatabase

app = Flask(__name__)

# =====================================================================
# 1. PASTE YOUR REAL PASSWORD FROM THE DOWNLOADED .TXT FILE ON LINE 12
# =====================================================================
NEO4J_URI = "neo4j+ssc://efa94ecb.databases.neo4j.io"
NEO4J_USER = "efa94ecb"
NEO4J_PASSWORD = "NuIUuBllss-ZgF8QFgyNhSBsMdZizmyOqZNNoKnGoY4"  # <--- REPLACE THIS!

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

COMPATIBILITY_RULES = {
    "O-":  ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
    "O+":  ["O+", "A+", "B+", "AB+"],
    "A-":  ["A-", "A+", "AB-", "AB+"],
    "A+":  ["A+", "AB+"],
    "B-":  ["B-", "B+", "AB-", "AB+"],
    "B+":  ["B+", "AB+"],
    "AB-": ["AB-", "AB+"],
    "AB+": ["AB+"]
}

SAMPLE_DONORS = [
    {"name": "Aarav Kulkarni", "phone": "9823011223", "bg": "O-",  "area": "Kothrud"},
    {"name": "Riya Deshmukh",  "phone": "9823044556", "bg": "A-",  "area": "Kothrud"},
    {"name": "Kabir Joshi",    "phone": "9823077889", "bg": "A+",  "area": "Kothrud"},
    {"name": "Sneha Patil",    "phone": "9823099001", "bg": "B+",  "area": "Deccan"},
    {"name": "Vikram Nair",    "phone": "9765012345", "bg": "O+",  "area": "Deccan"},
    {"name": "Ananya Sharma",  "phone": "9765054321", "bg": "AB+", "area": "Viman Nagar"}
]


def seed_database_now():
    """Seeds the 8 BloodGroup nodes, 27 edges, and 6 sample donors into Neo4j."""
    pairs = [
        {"from_bg": donor_bg, "to_bg": rec_bg}
        for donor_bg, rec_list in COMPATIBILITY_RULES.items()
        for rec_bg in rec_list
    ]
    with driver.session() as session:
        session.run("""
            UNWIND $pairs AS pair
            MERGE (b1:BloodGroup {type: pair.from_bg})
            MERGE (b2:BloodGroup {type: pair.to_bg})
            MERGE (b1)-[:CAN_DONATE_TO]->(b2)
        """, pairs=pairs)

        session.run("""
            UNWIND $donors AS d
            MERGE (bg:BloodGroup {type: d.bg})
            MERGE (area:CampusArea {name: d.area})
            MERGE (donor:Donor {name: d.name, phone: d.phone})
            MERGE (donor)-[:HAS_BLOOD_GROUP]->(bg)
            MERGE (donor)-[:LIVES_IN]->(area)
        """, donors=SAMPLE_DONORS)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/init_graph", methods=["POST"])
def init_graph():
    try:
        seed_database_now()
        return jsonify({"ok": True, "message": "Seeded 8 BloodGroup nodes, 27 edges, and 6 sample donors!"})
    except Exception as e:
        print("\n❌ NEO4J SEED ERROR:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/register", methods=["POST"])
def register_donor():
    data = request.json
    try:
        with driver.session() as session:
            session.run("""
                MERGE (bg:BloodGroup {type: $blood_group})
                MERGE (area:CampusArea {name: $area})
                MERGE (d:Donor {name: $name, phone: $phone})
                MERGE (d)-[:HAS_BLOOD_GROUP]->(bg)
                MERGE (d)-[:LIVES_IN]->(area)
            """, name=data["name"], phone=data["phone"], blood_group=data["blood_group"], area=data["area"])
        return jsonify({"ok": True, "message": f"Added {data['name']} ({data['blood_group']}) in {data['area']}!"})
    except Exception as e:
        print("\n❌ NEO4J REGISTER ERROR:", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/search", methods=["GET"])
def search_donors():
    needed_bg = request.args.get("blood_group", "A+")
    area = request.args.get("area", "Kothrud")

    cypher_query = """
    MATCH (d:Donor)-[:LIVES_IN]->(a:CampusArea {name: $area})
    MATCH (d)-[:HAS_BLOOD_GROUP]->(donor_bg:BloodGroup)-[:CAN_DONATE_TO]->(target_bg:BloodGroup {type: $needed_bg})
    RETURN d.name AS name,
           d.phone AS phone,
           donor_bg.type AS donor_blood_group,
           a.name AS area,
           CASE WHEN donor_bg.type = $needed_bg THEN 'EXACT' ELSE 'CROSS_COMPATIBLE' END AS match_type
    ORDER BY match_type DESC, donor_blood_group ASC
    """
    try:
        with driver.session() as session:
            result = session.run(cypher_query, needed_bg=needed_bg, area=area)
            donors = [record.data() for record in result]
        return jsonify({"ok": True, "needed": needed_bg, "area": area, "matches": donors})
    except Exception as e:
        print("\n❌ NEO4J SEARCH ERROR:", e)
        return jsonify({"ok": False, "error": str(e), "matches": []}), 500


@app.route("/api/stats", methods=["GET"])
def get_stats():
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
            edges = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
        return jsonify({"ok": True, "nodes": nodes, "edges": edges})
    except Exception as e:
        print("\n❌ NEO4J STATS ERROR:", e)
        return jsonify({"ok": False, "error": str(e), "nodes": 0, "edges": 0}), 500


if __name__ == "__main__":
    print("\n=======================================================")
    print("🔌 Testing connection to Neo4j AuraDB (pulse-db)...")
    try:
        seed_database_now()
        print("✅ SUCCESS! Connected to pulse-db and auto-seeded data!")
    except Exception as err:
        print("❌ CONNECTION FAILED! Reason:", err)
        print("👉 Check NEO4J_PASSWORD on Line 12 of app.py!")
    print("=======================================================\n")
    app.run(port=5000, debug=True)