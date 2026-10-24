# 1. Imports, Setup & Database Connection

from flask import Flask, render_template, jsonify , request, session
from neo4j import GraphDatabase

app = Flask(__name__)

NEO4J_URI = "neo4j+s://efa94ecb.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "NuIUuBllss-ZgF8QFgyNhSBsMdZizmyOqZNNoKnGoY4"

driver = GraphDatabase.driver(NEO4J_URI,auth = (NEO4J_USERNAME, NEO4J_PASSWORD))

@app.route("/")
def home():
    return render_template('index.html')

# 2. Initializing the Graph (/api/init_graph)

@app.route("/api/init_graph",methods = ["POST"])

def init_graph():
# Official biological red-blood-cell compatibility map
    compatibility_map = {
        "O-": [ "O-","O+","A+","A-","B+","B-","AB+","AB-"],
        "O+": [ "O+","A+","B+","AB+"],
        "A-": [ "A-","A+","AB-","AB+"],
        "A+": [ "A+","AB+"],
        "B-": [ "B-","B+","AB-","AB+"],
        "B+": [ "B+","AB+"],
        "AB-": [ "AB-","AB+"],
        "AB+": [ "AB+"]
    }

    sample_donors = [
        {"Name": "Aarav Kulkarani","Contact": "9823011223","Blood_Group": "O-","Area": "Kothrud"},
        {"Name": "Riya Deshmukh",  "Contact": "9823044556", "Blood_Group": "A-",  "Area": "Kothrud"},
        {"Name": "Kabir Joshi",    "Contact": "9823077889", "Blood_Group": "A+",  "Area": "Kothrud"},
        {"Name": "Sneha Patil",    "Contact": "9823099001", "Blood_Group": "B+",  "Area": "Kothrud"},
        {"Name": "Vikram Nair",    "Contact": "9765012345", "Blood_Group": "O+",  "Area": "Deccan"},
        {"Name": "Ananya Sharma",  "Contact": "9765054321", "Blood_Group": "AB+", "Area": "Viman Nagar"}
    ]

    with driver.session() as session:
        for donor_bg , recipient_list in compatibility_map.items():
            for recipient_bg in recipient_list:
                session.run("""
                    MERGE (b1:BloodGroup {type: $from_bg})
                    MERGE (b2:BloodGroup {type: $to_bg})
                    MERGE (b1)-[:CAN_DONATE_TO]->(b2)
                """, {"from_bg": donor_bg, "to_bg": recipient_bg})

        for d in sample_donors:
            session.run("""
                MATCH (blood_group:BloodGroup {type: $blood_group})
                MERGE (area:CampusArea {name: $area})
                MERGE (donor:Donor {name: $name, contact: $contact})
                MERGE (donor)-[:HAS_BLOOD_GROUP]->(blood_group)
                MERGE (donor)-[:LIVES_IN]->(area)
            """, name = d["Name"], contact = d["Contact"], blood_group = d["Blood_Group"], area = d["Area"])

    return jsonify({"message":" 8 Graph nodes, compatibility edges and sample donors initiialized!!"})

# 3. Registering a New Donor (/api/register)

@app.route("/api/register",methods = ["POST"])

def register_donor():
    data =  request.json

    query = """MATCH (bg:BloodGroup {type: $blood_group})
    MERGE (area:CampusArea {name: $area})
    CREATE (d:Donor {name: $name, contact: $contact})
    CREATE (d)-[:HAS_BLOOD_GROUP]->(bg)
    CREATE (d)-[:LIVES_IN]->(area)
    RETURN d.name AS name
    """

    with driver.session() as session:
        session.run(query, name = data["name"], contact = data["contact"], blood_group = data["blood_group"], area = data["area"])

        return jsonify({"message": f"Donor {data['name']} linked to {data['blood_group']} and {data['area']}!"})

# 4. Finding Compatible Donors via Graph Traversal (/api/search)

@app.route("/api/search", methods = ["GET"])

def search_donors():

    needed_bg = request.args.get("blood_group","A+")
    area = request.args.get("area","Kothrud")

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
    with driver.session() as session:
        result = session.run(cypher_query, needed_bg = needed_bg, area = area)
        donors = [record.data() for record in result]

    return jsonify({"needed": needed_bg, "area": area, "matches": donors})

# 5. Live Graph Statistics (/api/stats) & Server Launch

@app.route("/api/stats", methods = ["GET"])

def get_stats():
    with driver.session() as session:
        nodes = session.run("MATCH (n) RETURN count(n) AS count".single()["count"])
        edges =  session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
    return jsonify({"nodes": nodes, "edges": edges})


if __name__ == "__main__":
    app.run(port = 5000, debug = True)




