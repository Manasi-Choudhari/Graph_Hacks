from db import get_graph
import tools

g = get_graph()
res = tools.find_fraud_rings("MULE_0289f389", 3)
print("find_fraud_rings:", len(res["nodes"]), "nodes,", len(res["edges"]), "edges")
