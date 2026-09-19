import sys; sys.path.insert(0, "/Users/ran/Documents/marketdx/mcp-jev")
import server

# Stub the (already-verified, frozen) resolver so we test ONLY the new wiring/routing deterministically.
CANNED = {
    "semiconductors": {"status":"resolved","axis":"theme","refs":[{"type":"theme","id":56000000,"name":"Semiconductors","prob":0.92}],"indirect":False},
    "banks":          {"status":"resolved","axis":"gics","refs":[{"type":"gics","id":"4010","name":"Banks","prob":0.93},{"type":"gics","id":"40203010","name":"Asset Mgmt","prob":0.7}],"indirect":False},
    "retail":         {"status":"resolved","axis":"gics","refs":[{"type":"gics","id":"2550","name":"Cons Disc Retail","prob":0.8},{"type":"gics","id":"301010","name":"Cons Staples Retail","prob":0.75}],"indirect":False},
    "ai":             {"status":"resolved","axis":"theme","refs":[{"type":"theme","id":10000000,"name":"AI","prob":0.9}],"indirect":False},
    "my favorite":    {"status":"no_match","query":"my favorite","reason":"not an industry/theme","candidates":[]},
}
server._resolve_concept = lambda c: dict(CANNED[" ".join(str(c).strip().lower().split())])

def show(label, val):
    g,t,cf,rm = server._scope_resolve(val)
    print(f"{label:34s} gics={g} themes={t} confirm={'YES' if cf else '-'} map_keys={list(rm)}")
    return g,t,cf,rm

print("=== _scope_resolve type-routing (stubbed resolver) ===")
# theme concept → theme leg only
g,t,cf,_ = show("'semiconductors'", "semiconductors");            assert g==[] and t==[56000000] and not cf
# gics multi-home → two codes
g,t,cf,_ = show("'banks'", "banks");                              assert g==["4010","40203010"] and t==[] and not cf
# CSV compound: bank + AI → gics leg + theme leg together
g,t,cf,_ = show("'banks,ai' (compound)", "banks,ai");             assert g==["4010","40203010"] and t==[10000000] and not cf
# list form
g,t,cf,_ = show("['retail','semiconductors'] (list)", ["retail","semiconductors"]); assert g==["2550","301010"] and t==[56000000] and not cf
# pure-digit passthrough (raw gics code)
g,t,cf,_ = show("'45' (raw code)", "45");                         assert g==["45"] and t==[] and not cf
# raw code mixed with concept
g,t,cf,_ = show("'45,ai'", "45,ai");                              assert g==["45"] and t==[10000000] and not cf
# unresolved → ONE confirm envelope, no partial scope leaked
g,t,cf,rm = show("'my favorite' (no_match)", "my favorite");      assert g==[] and t==[] and cf and cf.get("needs_confirmation")
# compound where ONE token fails → whole thing returns confirm (honest, no silent partial)
g,t,cf,rm = show("'banks,my favorite'", "banks,my favorite");     assert cf and "my favorite" in cf["confirm"] and g==[] and t==[]
print("\n✅ ALL wiring assertions passed — type-routing, multi-home, compound CSV/list, raw-code passthrough, honest confirm.")
