import os
import certifi
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from neo4j import GraphDatabase
from pymongo import MongoClient
from dotenv import load_dotenv

# Loads your secret credentials from the .env file locally
load_dotenv()

app = Flask(__name__)

# 1. NEO4J AURADB CONNECTION (GRAPH DATABASE)
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# 2. MONGODB ATLAS CONNECTION (DOCUMENT DATABASE)
MONGO_URI = os.environ.get("MONGO_URI")
mongo_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
mongo_db = mongo_client["pulse_mongodb"]
profiles_col = mongo_db["donor_profiles"]
logs_col = mongo_db["search_logs"]

def is_mongo_online():
    try:
        mongo_client.admin.command("ping")
        return True
    except Exception:
        return False

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

def seed_database_now():
    """Seeds both Neo4j (Graph nodes/edges) and MongoDB (Medical Screening JSONs)."""
    pairs = []
    for donor_bg, recipients in COMPATIBILITY_RULES.items():
        for recipient_bg in recipients:
            pairs.append({"from_bg": donor_bg, "to_bg": recipient_bg})

    sample_donors = [
        {"name": "Aarav Kulkarni", "phone": "9823011223", "bg": "O-",  "area": "Kothrud",     "note": "Hb 15.1 g/dL • 68 kg • Universal Donor"},
        {"name": "Riya Deshmukh",  "phone": "9823044556", "bg": "A-",  "area": "Kothrud",     "note": "Hb 13.4 g/dL • 56 kg • Eligible Now"},
        {"name": "Kabir Joshi",    "phone": "9823077889", "bg": "A+",  "area": "Kothrud",     "note": "Hb 14.6 g/dL • 71 kg • No Allergies"},
        {"name": "Sneha Patil",    "phone": "9765011223", "bg": "B+",  "area": "Deccan",      "note": "Hb 13.8 g/dL • 58 kg • Eligible Now"},
        {"name": "Vikram Shinde",  "phone": "9765099887", "bg": "O+",  "area": "Deccan",      "note": "Hb 14.9 g/dL • 74 kg • Last donated 5m ago"},
        {"name": "Ananya Sharma",  "phone": "9123456780", "bg": "AB+", "area": "Viman Nagar", "note": "Hb 13.2 g/dL • 55 kg • Verified Student"}
    ]

    # 1. Seed Neo4j Graph
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
        """, donors=sample_donors)

    # 2. Seed MongoDB Donor Medical Screening Profiles
    mongo_ok = is_mongo_online()
    for d in sample_donors:
        doc = {
            "name": d["name"],
            "phone": d["phone"],
            "blood_group": d["bg"],
            "area": d["area"],
            "medical_note": d["note"],
            "verified": True,
            "disabled": False,
            "disabled_until": None,
            "updated_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        fallback_profiles[d["phone"]] = doc
        if mongo_ok:
            profiles_col.update_one({"phone": d["phone"]}, {"$set": doc}, upsert=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/init_graph", methods=["POST"])
def init_graph():
    try:
        seed_database_now()
        return jsonify({"status": "success", "message": "Neo4j Graph & MongoDB Profiles seeded!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/register", methods=["POST"])
def register_donor():
    data = request.json
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    blood_group = data.get("blood_group", "").strip()
    area = data.get("area", "").strip()
    medical_note = data.get("medical_note", "").strip() or "Hb > 13.0 g/dL • Weight > 50kg • Eligible"

    if not all([name, phone, blood_group, area]):
        return jsonify({"status": "error", "message": "Name, Phone, Blood Group, and Area are required."}), 400

    try:
        # 1. Create Node & Relationships in Neo4j
        with driver.session() as session:
            session.run("""
                MERGE (bg:BloodGroup {type: $blood_group})
                MERGE (area:CampusArea {name: $area})
                MERGE (d:Donor {name: $name, phone: $phone})
                MERGE (d)-[:HAS_BLOOD_GROUP]->(bg)
                MERGE (d)-[:LIVES_IN]->(area)
            """, name=name, phone=phone, blood_group=blood_group, area=area)

        # 2. Save Flexible Medical Screening JSON Document in MongoDB
        doc = {
            "name": name,
            "phone": phone,
            "blood_group": blood_group,
            "area": area,
            "medical_note": medical_note,
            "verified": True,
            "disabled": False,
            "disabled_until": None,
            "updated_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        fallback_profiles[phone] = doc
        if is_mongo_online():
            profiles_col.update_one({"phone": phone}, {"$set": doc}, upsert=True)

        return jsonify({"status": "success", "message": f"{name} added to Neo4j Graph & MongoDB Profiles!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/donor/update", methods=["POST", "PUT"])
def update_donor():
    """Simultaneously updates a person's profile in Neo4j Graph and MongoDB Document store."""
    data = request.json or {}
    old_phone = (data.get("old_phone") or data.get("phone") or "").strip()
    phone = (data.get("phone") or old_phone).strip()
    name = data.get("name", "").strip()
    blood_group = data.get("blood_group", "").strip()
    area = data.get("area", "").strip()
    medical_note = data.get("medical_note", "").strip() or "Hb > 13.0 g/dL • Weight > 50kg • Eligible"

    if not all([old_phone, name, phone, blood_group, area]):
        return jsonify({"status": "error", "message": "Name, Phone, Blood Group, and Area are required."}), 400

    try:
        # 1. Update in Neo4j Graph Database
        with driver.session() as session:
            session.run("""
                MERGE (d:Donor {phone: $old_phone})
                SET d.name = $name, d.phone = $phone
                WITH d
                OPTIONAL MATCH (d)-[r1:HAS_BLOOD_GROUP]->()
                DELETE r1
                WITH d
                MERGE (bg:BloodGroup {type: $blood_group})
                MERGE (d)-[:HAS_BLOOD_GROUP]->(bg)
                WITH d
                OPTIONAL MATCH (d)-[r2:LIVES_IN]->()
                DELETE r2
                WITH d
                MERGE (area:CampusArea {name: $area})
                MERGE (d)-[:LIVES_IN]->(area)
            """, old_phone=old_phone, phone=phone, name=name, blood_group=blood_group, area=area)

        # 2. Update in MongoDB Document Database
        doc = {
            "name": name,
            "phone": phone,
            "blood_group": blood_group,
            "area": area,
            "medical_note": medical_note,
            "verified": True,
            "updated_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }

        mongo_ok = is_mongo_online()
        if old_phone != phone:
            fallback_profiles.pop(old_phone, None)
            if mongo_ok:
                profiles_col.delete_one({"phone": old_phone})
        else:
            # Preserve existing disabled state when editing other profile fields
            existing = fallback_profiles.get(phone, {})
            if mongo_ok:
                existing_mongo = profiles_col.find_one({"phone": phone}, {"_id": 0}) or {}
                existing = existing_mongo or existing
            doc["disabled"] = existing.get("disabled", False)
            doc["disabled_until"] = existing.get("disabled_until", None)

        if "disabled" not in doc:
            doc["disabled"] = False
            doc["disabled_until"] = None

        fallback_profiles[phone] = doc
        if mongo_ok:
            profiles_col.update_one({"phone": phone}, {"$set": doc}, upsert=True)

        return jsonify({
            "status": "success",
            "message": f"Updated {name}'s profile simultaneously in Neo4j & MongoDB!",
            "donor": doc
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/donors", methods=["GET"])
def get_all_donors():
    """Returns all donors enriched with Neo4j graph relationships and MongoDB screening profiles."""
    donors = []
    known_phones = set()

    # 1. Try Neo4j first
    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Donor)
                OPTIONAL MATCH (d)-[:HAS_BLOOD_GROUP]->(bg:BloodGroup)
                OPTIONAL MATCH (d)-[:LIVES_IN]->(a:CampusArea)
                RETURN d.name AS name, d.phone AS phone, bg.type AS blood_group, a.name AS area
                ORDER BY d.name ASC
            """)
            donors = [dict(record) for record in result]
            for d in donors:
                if d.get("phone"):
                    known_phones.add(d["phone"])
    except Exception as e:
        print(f"[Neo4j] get_all_donors notice: {e}")

    # 2. Enrich from MongoDB profiles and fall back seamlessly
    try:
        mongo_ok = is_mongo_online()
        for d in donors:
            profile = None
            if mongo_ok:
                profile = profiles_col.find_one({"phone": d["phone"]}, {"_id": 0})
            if not profile:
                profile = fallback_profiles.get(d["phone"])
            d["medical_note"] = profile.get("medical_note") if profile else "Hb > 13.0 g/dL • Weight > 50kg • Eligible"
            d["disabled"] = bool(profile.get("disabled", False)) if profile else False
            d["disabled_until"] = profile.get("disabled_until") if profile else None

        # 3. Always include any donors present in MongoDB (resilient to Neo4j connection drops)
        mongo_profiles = list(profiles_col.find({}, {"_id": 0})) if mongo_ok else list(fallback_profiles.values())
        for p in mongo_profiles:
            if p.get("phone") and p["phone"] not in known_phones:
                donors.append({
                    "name": p.get("name", ""),
                    "phone": p.get("phone", ""),
                    "blood_group": p.get("blood_group", ""),
                    "area": p.get("area", ""),
                    "medical_note": p.get("medical_note", "Hb > 13.0 g/dL • Weight > 50kg • Eligible"),
                    "disabled": bool(p.get("disabled", False)),
                    "disabled_until": p.get("disabled_until", None)
                })
                known_phones.add(p["phone"])

        donors.sort(key=lambda x: (x.get("name") or "").lower())
        resp = jsonify({"status": "success", "donors": donors})
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/donor/<phone>", methods=["GET", "DELETE"])
def donor_detail(phone):
    """Read or Delete donor profile simultaneously in Neo4j and MongoDB."""
    phone = phone.strip()
    if request.method == "GET":
        try:
            record = None
            try:
                with driver.session() as session:
                    record = session.run("""
                        MATCH (d:Donor {phone: $phone})
                        OPTIONAL MATCH (d)-[:HAS_BLOOD_GROUP]->(bg:BloodGroup)
                        OPTIONAL MATCH (d)-[:LIVES_IN]->(a:CampusArea)
                        RETURN d.name AS name, d.phone AS phone, bg.type AS blood_group, a.name AS area
                    """, phone=phone).single()
            except Exception as e:
                print(f"[Neo4j] donor_detail notice: {e}")

            profile = profiles_col.find_one({"phone": phone}, {"_id": 0}) if is_mongo_online() else fallback_profiles.get(phone)

            if not record and not profile:
                return jsonify({"status": "error", "message": "Donor not found"}), 404

            d = dict(record) if record else {}
            if profile:
                if not d.get("name"): d["name"] = profile.get("name", "")
                if not d.get("phone"): d["phone"] = profile.get("phone", phone)
                if not d.get("blood_group"): d["blood_group"] = profile.get("blood_group", "")
                if not d.get("area"): d["area"] = profile.get("area", "")
                d["medical_note"] = profile.get("medical_note", "Verified • Standard Eligibility")
                d["disabled"] = bool(profile.get("disabled", False))
                d["disabled_until"] = profile.get("disabled_until", None)
            else:
                d["medical_note"] = "Verified • Standard Eligibility"
                d["disabled"] = False
                d["disabled_until"] = None

            resp = jsonify({"status": "success", "donor": d})
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    elif request.method == "DELETE":
        try:
            with driver.session() as session:
                session.run("MATCH (d:Donor {phone: $phone}) DETACH DELETE d", phone=phone)

            fallback_profiles.pop(phone, None)
            if is_mongo_online():
                profiles_col.delete_one({"phone": phone})

            return jsonify({"status": "success", "message": f"Donor {phone} deleted from Neo4j & MongoDB."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/donor/toggle-status", methods=["POST"])
def toggle_donor_status():
    """Disable (for up to 6 months) or revive a donor account in MongoDB.
    Disabled donors are excluded from Neo4j traversal search results.
    When disabled_until expires, the donor is auto-revived on the next search.
    """
    data = request.json or {}
    phone = (data.get("phone") or "").strip()
    action = (data.get("action") or "").strip().lower()   # "disable" or "revive"
    months = int(data.get("months") or 1)

    if not phone or action not in ("disable", "revive"):
        return jsonify({"status": "error", "message": "phone and action ('disable'|'revive') are required."}), 400

    months = max(1, min(months, 6))   # Clamp to 1–6 months

    try:
        if action == "disable":
            disabled_until = (datetime.now() + timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%S")
            patch = {
                "disabled": True,
                "disabled_until": disabled_until,
                "updated_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
            }
            msg = f"Account paused for {months} month{'s' if months > 1 else ''}. Revives on {datetime.strptime(disabled_until, '%Y-%m-%dT%H:%M:%S').strftime('%d %b %Y')}."
        else:  # revive
            patch = {
                "disabled": False,
                "disabled_until": None,
                "updated_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
            }
            msg = "Account reactivated successfully."

        # Update MongoDB document
        if phone in fallback_profiles:
            fallback_profiles[phone].update(patch)
        mongo_ok = is_mongo_online()
        if mongo_ok:
            result = profiles_col.update_one({"phone": phone}, {"$set": patch})
            if result.matched_count == 0:
                return jsonify({"status": "error", "message": "Donor not found in MongoDB."}), 404
        elif phone not in fallback_profiles:
            return jsonify({"status": "error", "message": "Donor not found."}), 404

        return jsonify({
            "status": "success",
            "message": msg,
            "disabled": patch["disabled"],
            "disabled_until": patch.get("disabled_until")
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/search", methods=["GET"])
def search_compatible_donors():
    needed_bg = request.args.get("blood_group", "A+")
    area = request.args.get("area", "Kothrud")
    log_search = request.args.get("log", "true") == "true"

    try:
        # 1. Graph Traversal in Neo4j
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Donor)-[:LIVES_IN]->(a:CampusArea {name: $area})
                MATCH (d)-[:HAS_BLOOD_GROUP]->(donor_bg:BloodGroup)-[:CAN_DONATE_TO]->(target_bg:BloodGroup {type: $needed_bg})
                RETURN d.name AS name, 
                       d.phone AS phone, 
                       donor_bg.type AS donor_blood_group, 
                       a.name AS area,
                       CASE WHEN donor_bg.type = $needed_bg THEN 'EXACT' ELSE 'CROSS_COMPATIBLE' END AS match_type
                ORDER BY match_type DESC, donor_blood_group ASC
            """, needed_bg=needed_bg, area=area)

            donors = [dict(record) for record in result]

        # 2. Enrich Each Matched Donor With Medical Profile from MongoDB
        # Also auto-revive donors whose disable period has expired, and filter out still-disabled ones
        mongo_ok = is_mongo_online()
        now = datetime.now()
        active_donors = []
        for d in donors:
            profile = None
            if mongo_ok:
                profile = profiles_col.find_one({"phone": d["phone"]}, {"_id": 0})
            if not profile:
                profile = fallback_profiles.get(d["phone"])

            # Auto-revive: if disabled_until has passed, clear the disabled flag
            if profile:
                disabled_until = profile.get("disabled_until")
                if disabled_until and profile.get("disabled", False):
                    try:
                        expiry = datetime.strptime(disabled_until, "%Y-%m-%dT%H:%M:%S")
                        if now >= expiry:
                            revive_patch = {"disabled": False, "disabled_until": None}
                            if profile.get("phone"):
                                fallback_profiles.get(profile["phone"], {}).update(revive_patch)
                            if mongo_ok:
                                profiles_col.update_one({"phone": d["phone"]}, {"$set": revive_patch})
                            profile["disabled"] = False
                            profile["disabled_until"] = None
                    except (ValueError, TypeError):
                        pass

            # Skip donors who are still disabled
            if profile and profile.get("disabled", False):
                continue

            d["medical_note"] = profile.get("medical_note") if profile else "Verified • Standard Eligibility"
            d["disabled"] = False
            active_donors.append(d)

        donors = active_donors

        # 3. Automatically Insert Search Audit Log into MongoDB
        if log_search:
            log_entry = {
                "needed_bg": needed_bg,
                "area": area,
                "matches_count": len(donors),
                "matched_donors": [d["name"] for d in donors],
                "timestamp": datetime.now().strftime("%I:%M:%S %p")
            }
            fallback_logs.insert(0, log_entry)
            if mongo_ok:
                logs_col.insert_one(dict(log_entry))

        return jsonify({"status": "success", "matches": donors})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/logs", methods=["GET"])
def get_search_logs():
    try:
        if is_mongo_online():
            logs = list(logs_col.find({}, {"_id": 0}).sort("_id", -1).limit(5))
            return jsonify({"status": "success", "logs": logs})
        return jsonify({"status": "success", "logs": fallback_logs[:5]})
    except Exception as e:
        return jsonify({"status": "error", "logs": fallback_logs[:5]})


@app.route("/api/stats", methods=["GET"])
def graph_stats():
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
            edges = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]

        if is_mongo_online():
            mongo_docs = profiles_col.count_documents({}) + logs_col.count_documents({})
        else:
            mongo_docs = len(fallback_profiles) + len(fallback_logs)

        return jsonify({"nodes": nodes, "edges": edges, "mongo_docs": mongo_docs})
    except Exception:
        return jsonify({"nodes": 0, "edges": 0, "mongo_docs": 0})


if __name__ == "__main__":
    print("\n========================================================")
    print("🔌 Testing connections to Neo4j AuraDB & MongoDB...")
    try:
        driver.verify_connectivity()
        seed_database_now()
        print("✅ NEO4J CONNECTED & SEEDED SUCCESSFULLY!")
    except Exception as e:
        print(f"❌ NEO4J CONNECTION FAILED! Reason: {e}")

    if is_mongo_online():
        print("✅ MONGODB COMPASS CONNECTED (Database: pulse_mongodb)!")
    else:
        print("⚠️ Local MongoDB not detected yet — running with seamless fallback until MongoDB starts.")
    print("========================================================\n")

    app.run(debug=True, port=5000)
