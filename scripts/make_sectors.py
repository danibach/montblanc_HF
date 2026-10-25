"""Make site/sector-points.js: the flying sectors of the map (Sarah, 25 October 2026), as pilots name them.

A sector is a name and its communes, as the FFVL file writes them (« Saint Hilaire du Touvet »; « Verdun@09 » when two
departments have a commune of that name), plus points of its own where the FFVL has none (Switzerland, take-offs
found from the outings). Its points are the FFVL take-offs of those communes; on the map a take-off belongs to the
sector of the nearest point within MAX_KM (site/sectors.js). To move a take-off to another sector, move its commune.

    python scripts/make_sectors.py              # today's FFVL file from data.gouv.fr
    python scripts/make_sectors.py terrains.json
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mbhf.sites import ffvl_takeoffs  # noqa: E402

OUT = ROOT / "site" / "sector-points.js"

# (name, communes, points of its own [lat, lon])
SECTORS = [
    # Haute-Savoie, Savoie
    ("Lac d'Annecy", ["Talloires", "Talloires-Montmin", "Montmin", "Lathuile", "Seythenex", "Marlens", "Viuz-la-Chiesaz"],
     [[45.853, 6.223], [45.828, 6.287], [45.775, 6.292], [45.815, 6.187], [45.796, 6.104], [45.730, 6.196]]),
    ("Aravis", ["La Clusaz", "Le Grand Bornand"],
     [[45.893, 6.408], [45.890, 6.460], [45.909, 6.508], [45.924, 6.530], [45.870, 6.441], [45.826, 6.370], [45.804, 6.418], [45.959, 6.477]]),
    ("Bornes – Parmelan", ["Naves Parmelan"], [[46.020, 6.346], [45.960, 6.242], [46.043, 6.419]]),
    ("Salève", ["Pas de l'Echelle", "Collonge sous Saleve", "Bossey"], [[46.149, 6.189]]),
    ("Chablais", ["Thollon", "Thollon les Memises", "Thonon", "Orcier", "Chatel", "Morzine Avoriaz"], [[46.106, 6.455]]),
    ("Giffre – Grand Massif", ["Mieussy", "Samoens", "Les Carroz - Araches la Frasse", "St Sigismond"], [[46.116, 6.721]]),
    ("Passy – Megève", ["Passy", "Cordon", "Megeve"], []),
    ("Chamonix – Mont-Blanc", ["Chamonix", "Les Houches", "Argentiere", "Chamonix Argentiere", "Chamonix-Mont-Blanc", "Servoz"],
     [[45.833, 6.865], [46.023, 6.851]]),
    ("Saint-Gervais – Les Contamines", ["St Gervais Mont Blanc", "Saint Gervais les Bains", "Les Contamines Montjoie",
                                        "Les Contamines Montjoie/Hauteluce"], []),
    ("Bauges", ["Les Deserts", "Notre Dame des Millieres", "Mercury", "Cruet", "Aillon-le-Jeune", "Aillon-le-Vieux", "Jarsy",
                "Doucy-en-Bauges", "Sainte-Reine", "Saint-Jean-de-la-Porte", "Montcel", "Pugny-Chatenod", "Saint-Offenge-Dessus",
                "Puygros"], [[45.689, 6.194], [45.646, 6.115]]),
    ("Lac du Bourget – Avant-Pays", ["Cessens", "Verel-Pragondran", "Saint-Maurice-de-Rotherens", "Verel de Montbel",
                                     "St Paul sur Yenne", "Nances"], []),
    ("Beaufortain – Val d'Arly", ["Areches", "Beaufort sur Doron", "Beaufort-sur-Doron", "Villard-sur-Doron", "Villard sur Doron",
                                  "Ugine", "Albertville"], []),
    ("Haute-Tarentaise", ["Bourg Saint Maurice", "Bourg-Saint-Maurice", "Montvalezan", "La Rosiere", "La Rosiere, Montvalezan",
                          "Sainte Foy Tarentaise", "Val-d'Isere", "Tignes", "Seez", "Peisey-Nancroix", "Landry", "Les Chapelles",
                          "Granier"], []),
    ("Tarentaise – Courchevel, Belleville", ["Bozel", "Macot-la-Plagne", "La Plagne", "La Perriere", "Saint-Bon-Courchevel",
                                              "Saint-Bon-Tarentaise", "Pralognan-la-Vanoise", "Les Belleville",
                                              "Saint-Jean-de-Belleville", "Saint-Martin-de-Belleville",
                                              "Les Avanchers-Valmorel", "Cevins", "La Bathie", "Naves@73"], []),
    ("Maurienne", ["Saint-Sorlin-d'Arves", "Montgellafrey", "Saint-Francois-Longchamp", "Jarrier", "Villarembert",
                   "Sainte-Marie-de-Cuines", "Albiez-Montrond", "Valloire", "Randens"], []),
    ("Haute-Maurienne", ["Aussois", "Bonneval-sur-Arc", "Valcenis", "Lanslevillard", "Villarodin-Bourget", "Modane", "Freney",
                         "Termignon"], []),
    # Ain, Jura, Doubs
    ("Bugey – Grand Colombier", ["Anglefort - Culoz", "Parves", "Innimond", "Saint Rambert", "Oncieu", "Torcieu", "Tenay",
                                 "Saint Sorlin", "Leyrieu", "Leyssard", "Champfromier", "Balvay", "Lalleyriat",
                                 "Chatillon en Michaille", "Port", "St Benoit"], []),
    ("Pays de Gex – Haut-Jura", ["Mijoux", "Vesancy", "Crozet", "Thoiry", "Lancrans", "Confort", "Les Rousses", "Septmoncel",
                                 "Lezat", "Cinquetral", "Saint-Claude", "Montcusel"], [[46.368, 6.080], [46.299, 5.983]]),
    ("Jura – Salins, Champagnole", ["Salins les Bains", "Salins-les-Bains", "Ney", "St Thiebaud", "Pretin", "Pannessieres", "Grusse",
                                    "La Chaux du Dombief", "Charezier", "Poligny"], []),
    ("Mont d'Or – Métabief", ["Longevilles Mont d'Or", "Jougne", "Metabief"], []),
    ("Haut-Doubs", ["Les Fins", "Montlebon", "Orchamps Vennes", "Arc sous Cicon", "Echevannes", "Vuillafans", "Les Gras",
                    "Orgeans-Blanchefontaine"], []),
    ("Besançon – Loue", ["Besancon", "Avanne-Aveney", "Vieilley", "Montfaucon", "Arguel", "Amathay-Vesigneux"], []),
    # Isère, Drôme
    ("Chartreuse – Saint-Hilaire", ["Saint Hilaire du Touvet", "Saint-Pancrasse", "St Pierre de Chartreuse",
                                    "Saint Pierre de Chartreuse", "Saint-Pierre-de-Chartreuse", "Voreppe", "La Buisse", "Sarcenas",
                                    "Mont-Saint-Martin", "Saint-Julien-de-Raz", "Saint-Pierre-d'Entremont"], []),
    ("Belledonne", ["Allevard", "St Pierre d'Allevard", "Arvillard", "Champlaurent", "Montendry", "Prapoutel - les 7 Laux",
                    "Revel", "Chamrousse", "Saint-Mury-Monteymont", "Poisat", "La Chapelle du Bard",
                    "Saint-Barthelemy-de-Sechilienne"], []),
    ("Vercors – Grenoble", ["Lans-en-Vercors", "Lans en Vercors", "Villard de Lans", "Autrans", "Meaudre", "Correncon en Vercos",
                            "Saint-Nizier-du-Moucherotte", "Engins", "Montaud", "Malleval", "Malleval en Vercors",
                            "Saint-Quentin-sur-Isere", "Saint-Paul-de-Varces", "Varces", "Claix", "Le Gua"], []),
    ("Trièves – Matheysine", ["Gresse en Vercors", "St Paul les Monestiers", "Saint-Baudille-et-Pipet", "St Baudille",
                              "Saint Arey", "Cordeac", "Laffrey", "Notre Dame de Vaux", "Saint-Honore",
                              "Villard-Saint-Christophe"], []),
    ("Oisans", ["Alpe d'Huez", "Huez", "Venosc", "Auris", "Vaujany", "Oris en Rattier", "Valbonnais", "Villard Reymond"], []),
    ("Vercors – Royans", ["Leoncel", "Oriol en Royans", "La Chapelle en Vercors", "Saint Jean en Royans", "St Martin en Vercors",
                          "St Pierre de Cherennes", "Peyrus"], []),
    ("Diois", ["Aurel", "Luc-en-Diois", "Lesches-en-Diois", "Die", "Montmaur-en-Diois", "Joncheres"], []),
    ("Baronnies – Drôme provençale", ["Mevouillon", "La Roche Saint Secret", "Sainte Jalle", "Vesc", "Nyons", "Villefranche",
                                      "Barret de Lioure", "Le Poet Sigilat", "Le Pegue", "Dieulefit", "Beauvoisin", "Eyzahut",
                                      "La Roche-sur-Grane"], []),
    ("Mont Ventoux", ["Beaumont du Ventoux", "Bedoin", "Malaucene", "Sault", "Monieux", "Gigondas", "St Hippolyte le Graveyron"], []),
    # Hautes-Alpes, Alpes-de-Haute-Provence, Alpes-Maritimes, Var, Bouches-du-Rhône
    ("Serre-Ponçon – Embrunais", ["Chorges", "La Batie Neuve", "Reallon", "Savines-le-Lac", "Theus", "Puy Sanieres", "Les Orres",
                                  "Montclar", "Saint-Vincent-les-Forts", "Piegut", "Chateauroux les Alpes"], []),
    ("Gapençais – Champsaur", ["Gap", "Rabou", "La Roche-des-Arnauds", "St Jean St Nicolas", "Saint-Jean-Saint-Nicolas", "Orcieres",
                               "St. Leger les Melezes", "La Motte-en-Champsaur", "Forest-Saint-Julien", "Le Noyer",
                               "Saint-Etienne-en-Devoluy"], []),
    ("Laragne – Buëch", ["Laragne", "La Faurie", "Oze", "Veynes", "Aspres", "Mereuil", "Saint-Genis", "La Beaume", "Montclus",
                         "Mison", "Melve"], []),
    ("Briançonnais – Écrins", ["Vallouise", "Pelvoux", "La Grave", "La-Salle-les-Alpes", "La Salle les Alpes", "St Chaffrey",
                               "Saint Chaffrey", "Puy-Saint-Pierre", "Le Monetier-les-Bains"], []),
    ("Queyras", ["Ceillac", "Arvieux"], []),
    ("Ubaye", ["Barcelonnette", "Uvernet-Fours"], []),
    ("Pays de Seyne", ["Selonnet", "Seyne"], []),
    ("Sisteron – Val de Durance", ["Saint-Geniez", "Mezien", "Valbelle"], []),
    ("Digne – Saint-André-les-Alpes", ["Digne-les-Bains", "Archail", "Saint Andre les Alpes", "Clumanc"], []),
    ("Montagne de Lure – Luberon", ["Banon", "L'Hospitalet", "Revest-des-Brousses", "Oraison", "Rustrel"], []),
    ("Verdon – Haut-Var", ["Moustiers-Sainte-Marie", "Sainte-Croix-de-Verdon", "Aiguines", "Bargeme", "Bargemon"], []),
    ("Gourdon – Gréolières", ["Greolieres", "Gourdon", "Saint-Vallier-de-Thiey", "Saint-Vallier-de Thiey", "Bar-sur-Loup",
                             "Andon-Thorenc", "Coursegoules", "Le Mas", "La Bastide", "La Roque Esclapon"], []),
    ("Valdeblore – Mercantour", ["Valdeblore"], []),
    ("Roya – Sospel", ["Sospel", "Tende", "Breil-sur-Roya"], []),
    ("Riviera – Menton", ["Roquebrune", "Peille", "Cantaron"], []),
    ("Marseille – Calanques", ["Marseille"], []),
    ("Sainte-Baume – Aubagne", ["Cuges-les-Pins", "Cuges les Pins", "Aubagne", "Gemenos", "Signes", "La Cadiere d'Azur",
                                "Plan-d'Aups-Saint-Baume"], []),
    ("Sainte-Victoire", ["Puyloubier", "Saint Ser", "Beaurecueil"], []),
    # Massif central
    ("Sancy – Mont-Dore", ["Le Mont Dore", "Mont Dore", "Chambon sur Lac", "Saint Diery", "Besse et St Anastaise", "Valbeleix",
                           "St-Pierre-Colamine", "St Pierre Colamine", "Saurier", "Orcival"], []),
    ("Puy de Dôme – Chaîne des Puys", ["Orcines", "Veyre-Monton", "St-Maurice Es Allier", "St Sandoux", "Vodable"], []),
    ("Cantal – Puy Mary", ["Dienne", "Le Claux", "Le Vaulmier", "Brezons", "Vic sur Cere", "Vic-sur-Cere", "Laveissiere",
                           "St Jacques des Blats", "Le Falgoux", "Mandailles - St Julien", "Mandailles", "Montgreleix"], []),
    ("Forez", ["Job", "Chatelneuf", "Cherier", "Laprugne"], []),
    ("Pilat", ["La Valla en Gier", "Burdignes", "Pelussin", "Veranne", "Chuyer", "Saint Desirat"], []),
    ("Mézenc – Gerbier", ["Chaudeyrolles", "Les Estables", "Boree", "Accons", "Saint Clement", "Saint Jean Roure"], []),
    ("Le Puy-en-Velay", ["Chaspinhac", "Polignac", "Lantriac", "Saint-Berain", "Roche-en-Regnier", "Retournac",
                         "Chamalieres-sur-Loire", "Saint-Didier-d'Allier", "Esplantas"], []),
    ("Ardèche – Tanargue", ["Valgorge", "Gravieres", "St Paul le Jeune", "Brahic"], []),
    ("Privas – Coiron", ["Privas", "Rochessauve", "Mirabel"], []),
    ("Beaujolais – Monts du Lyonnais", ["Quincie", "Ancy", "Saint-Forgeux", "St Etienne la Varenne", "Montrottier", "Letra",
                                        "Chevinay", "Longes", "Poleymieux au Mont d'Or", "Violay"], []),
    ("Cévennes – Lozère", ["Mende", "Barjac", "Quezac", "Ispagnac", "Saint-Bonnet-de-Chirac", "Les Salelles"], []),
    ("Millau – Grands Causses", ["Millau", "Tournemire", "Recoules-Previnquieres", "Severac le Chateau"], []),
    ("Rouergue – Vallon de Marcillac", ["Mouret", "Balsac", "Clairvaux-d'Aveyron", "Compolibat", "Vieillevie"], []),
    ("Monédières", ["Chaumeil", "Veix"], []),
    # Bourgogne, Franche-Comté (plateaux), Vosges, Alsace, nord-est
    ("Mâconnais – Solutré", ["Bussieres", "Blanot", "Tramayes", "Solutre-Pouilly", "Vergisson", "Berze la Ville", "Berze le Chatel",
                             "Cluny", "Saint Point", "Verze", "Mancey", "Cortambert", "Burnand", "Suin"], []),
    ("Côte d'Or – Dijon", ["Chassey-le-Camp", "Meloisey", "Cirey les Nolay", "Moroges", "Saint Denis de Vaux", "Bligny-sur-Ouche",
                           "Villars Fontaine", "Remilly-en-Montagne", "Velars sur Ouche", "Dijon", "Baulme la Roche",
                           "Savigny sous Malaîn", "Agey"], []),
    ("Morvan", ["Uchon", "Autun", "Saint Leger sous Beuvray", "Uxeau", "Issy l'Eveque"], []),
    ("Hautes-Vosges – La Bresse", ["La Bresse", "Saulxures", "Vagney", "Sapois", "Basse sur le Rupt", "Xonrupt-Longemer",
                                   "Le Menil", "Rupt sur Moselle", "Rupt-sur-Moselle", "St Etienne le Remiremont", "Vecoux"], []),
    ("Ballons des Vosges", ["St Maurice sur Moselle", "Bussang", "Fellering", "Fellering - le Treh", "Urbes", "St Amarin", "Sewen",
                            "Wildenstein", "Cernay", "Plancher les Mines", "Ste Marie en Chanois", "St Barthelemy",
                            "Saint-Barthelemy"], []),
    ("Vallée de Munster", ["Mittlach", "Muhlbach sur Munster", "Hohrod", "Le Gaschney"], []),
    ("Val d'Argent – Kaysersberg", ["Orbey", "Le Bonhomme", "Lapoutroie", "Ste Marie aux Mines", "Sainte Marie aux Mines",
                                    "Breitenbach", "Neubois"], []),
    ("Vallée de la Bruche – Vosges du Nord", ["Russ", "Reinhardsmunster", "Bouxwiller"], []),
    ("Meuse – Saint-Mihiel", ["Chauvoncourt", "Geville", "Chaillon", "Saint Mihiel", "Dompcevrin"], []),
    ("Haute-Marne", ["Vouecourt", "Bologne", "Dampierre", "Bourmont Entre Meuse et Mouzon", "Chauffourt", "Charmoilles",
                     "Thonnance-les-Joinville", "Thonnances les Joinville", "Soncourt sur Marne", "St Urbain - Maconcourt"], []),
    ("Ardennes – Vallée de la Meuse", ["Revin", "Rocroi", "Haybes", "Haulme", "Thilay", "Bogny sur Meuse", "Balaives", "Montherme",
                                       "Dom le Mesnil"], []),
    ("Montagne de Reims – Vallée de la Marne", ["Grauves", "Port A Binson", "Chamery", "Hermonville", "Vincelles", "Saint-Gilles",
                                                "Courcy", "Chezy sur Marne", "Mont Saint Pere", "Bonneil"], []),
    ("Pays des Trois Frontières", ["Haute-Kontz", "Contz-les-Bains", "Algrange", "Volmerange-les-Mines"], []),
    # Normandie, Hauts-de-France, Bretagne, Atlantique
    ("Côte d'Albâtre", ["Saint Pierre en Port", "Fecamp", "Eletot", "Saint Martin aux Buneaux", "Ganzeville", "Benouville",
                        "Saint Aubin sur Mer", "Ste Marguerite sur Mer", "Criel sur Mer", "Sainte Adresse", "Octeville"], []),
    ("Vallée de la Seine", ["Amfreville sous les Monts", "Les Andelys", "Tosny", "Fontaine sous Jouy", "La Roquette", "Louviers",
                            "Barneville sur Seine", "Henouville", "Roncherolles sur le Vivier", "Marbeuf",
                            "St Samson de la Roque", "Marais Vernier", "Manneville sur Risle"], []),
    ("Pays de Bray – Bresle", ["Londinieres", "Osmoy Saint Valery", "Osmoy St Valery", "Nesle Normandeuse",
                               "St Vaast d'Equiqueville", "Sainte Agathe d'Aliermont", "Le Mesnil Lieubray",
                               "St Germain sur Eaulne", "Rambures", "Auteuil", "Ons en Bray", "St Aubin en Bray"], []),
    ("Bessin – Côte de Nacre", ["Vierville sur Mer", "Commes", "Tracy sur Mer", "Port-en-Bessin-Huppain", "Colleville-sur-Mer",
                                "Luc sur Mer"], []),
    ("Côte Fleurie", ["Auberville", "Villerville"], []),
    ("Suisse normande", ["Saint-Omer@14", "St Martin de Sallen", "Pont d'Ouilly", "L'Oudon", "Ommeel", "Conde-sur-Vire"], []),
    ("Cotentin – La Hague", ["Vauville", "Siouville", "Omonville", "Greville", "Le Rozel", "Auderville", "Biville", "Carteret"], []),
    ("Granville – Baie du Mont-Saint-Michel", ["Carolles", "Champeaux", "Granville", "Donville"], []),
    ("Côte d'Opale", ["Frencq", "Equihen Plage", "Licques"], []),
    ("Crozon – Menez-Hom", ["Dineault", "Rosnoen", "Plonevez-Porzay", "Plonevez Porzay", "Plomodiern", "Saint Nic"], []),
    ("Monts d'Arrée", ["Botmeur", "Saint-Rivoal"], []),
    ("Trégor – Côte de Granit rose", ["Trebeurden", "Lannion", "Tredrez", "Saint Michel en Greve", "Perros Guirec",
                                      "Saint-Jean-du-Doigt"], []),
    ("Baie de Saint-Brieuc – Goëlo", ["Plerin", "Plouezec", "Plouha", "Ploubazlanec", "Pleneuf-Val-Andre",
                                      "Saint-Jacut-de-la-Mer"], []),
    ("Dune du Pilat – Médoc", ["La Teste de Buch", "Hourtin", "Naujac sur Mer", "Carcans", "Le Verdon-sur-Mer"], []),
    # Sud-Ouest, Pyrénées, Languedoc
    ("Vallée du Lot – Quercy", ["Luzech", "Douelle", "Crayssac", "Castelfranc", "Larnagol", "Cajarc", "Montbrun", "Saujac",
                                "Saint Vincent Rive d'Olt", "Ambeyrac"], []),
    ("Vallée de la Dordogne – Quercy", ["Floirac", "Creysse", "Lanzac", "Glanes", "Monceaux-sur-Dordogne", "Monceaux",
                                        "Saint-Paul-de-Loubressac"], []),
    ("Gorges de l'Aveyron – Saint-Antonin", ["St Antonin Noble Val", "Saint-Antonin-Noble-Val", "St Marcel de Campes",
                                             "Marnaves", "Vazerac"], []),
    ("Périgord – Vallée de la Vézère", ["Condat sur Vezere", "St Leon sur Vezere", "Aubas", "Coubjours", "Saint-Robert"], []),
    ("Montagne Noire", ["Dourgne", "Soreze", "Le Riols"], []),
    ("Pays basque", ["Macaye", "Macaye - Mendionde", "Anhaux", "Suhescun", "Bidarray", "Irouleguy", "Hosta", "Musculdy",
                     "Trois Villes", "Lacarry-Arhan-Charritte-de-Haut", "Guethary"], []),
    ("Vallées d'Aspe et d'Ossau", ["Accous", "Lees Athas", "Osse en Aspe", "Borce", "Escot", "Laruns", "Beost",
                                   "Lanne en Baretous"], []),
    ("Val d'Azun – Argelès", ["Gaillagos", "Arthez-d'Asson", "Aucun", "Ouzous", "Prechac", "Saint-Pe-de-Bigorre", "Ourdon",
                              "Berberust-Lias", "Beaucens", "Sacoue", "Vignet"], []),
    ("Barèges – Tourmalet – Campan", ["Sers", "Bareges", "Campan", "Grust", "Vizos", "Uz"], []),
    ("Vallée d'Aure – Saint-Lary", ["Saint Lary Soulan", "Vielle-Aure", "Aulon", "Ens", "Barrancoueu"], []),
    ("Luchon – Peyragudes", ["Gouaux de Larboust", "Gouaux-de-Larboust", "Luchon", "Montauban de Luchon", "Germ", "Adervielle",
                             "Genos", "Mont", "Garin", "Saint-Beat", "Boutx", "Marignac", "Cier-de-Riviere", "Juzet-d'Izaut"], []),
    ("Couserans – Arbas", ["Oust", "Moulis", "Cazavet", "Arrout", "Castillon", "Massat", "Arbas", "Soueich", "Herran", "Ausseing",
                           "Roquefort sur Garonne"], []),
    ("Haute-Ariège – Tarascon", ["Goulier", "Ganac", "Verdun@09", "Sem", "Orus", "Sengonac", "Belesta"], []),
    ("Pays de Sault", ["Roquefeuil", "Camurac", "Belcaire", "Coudons", "Ginoles"], []),
    ("Corbières – Fenouillèdes", ["Tuchan", "Duilhac sous Peyrepertuse", "Cucugnan", "Corneilla de la Riviere", "Tarerach",
                                  "Camplong-d'Aude", "Peyriac-de-Mer", "Leucate"], []),
    ("Cerdagne – Capcir", ["Osseja", "Valcebollere", "Targasonne", "Les Angles", "Sahorre"], []),
    ("Vallespir – Albères", ["Cerbere", "Sorede", "Ceret", "Camelas", "Arles-sur-Tech", "Corsavy"], []),
    ("Salagou – Lodévois", ["Cabrieres", "Valquieres", "Merifons", "Octon", "Liausson", "Soubes", "Joncels", "Les Prats",
                            "Saint Guiraud"], []),
    ("Pic Saint-Loup – Séranne", ["Saint Andre de Bueges", "Claret", "Pompignan", "Sumene", "Lauret"], []),
    ("Sète – La Gardiole", ["Frontignan", "Gigean", "Vic la Gardiole"], []),
    ("Haut-Languedoc – Orb", ["St Etienne d'Albagnan", "Graissessac", "Cessenon", "Lespignan", "Argeliers"], []),
    ("Gard – Mont Bouquet", ["Seynes", "Saint Come", "Calvisson", "St Dionisy", "Theziers", "Pujaut"], []),
    # plaines et collines
    ("Guéret – Monts de Guéret", ["St Sulpice@23", "St Leger le Gueretois", "La Chapelle Taillefert", "Sainte Feyre",
                                  "Soubrebost"], []),
    ("Vichy – Combrailles", ["Cusset", "Abrest", "Ussel-d'Allier", "Charroux", "Menat", "Saint Victor"], []),
    ("Yonne – Pays d'Othe", ["Arcy sur Cure", "St Martin sur Armancon", "Looze", "Bussy-en-Othe", "Sormery", "Noyers", "Veron",
                             "Saint More", "Malay le Grand", "Eaux Puiseaux", "Laines-aux-Bois", "Rigny-le-Ferron"], []),
    ("Châtillonnais", ["Athie", "Massingy", "Vix", "Neuville-sur-Seine", "Bar-sur-Aube"], []),
    ("Nivernais – Vaux d'Yonne", ["Asnan", "Grenois"], []),
    ("Haute-Saône – Vesoul", ["Echenoz la Meline", "Colombier", "Chariez", "Autrey les Cerre", "Grammont"], []),
    ("Lorraine – Côtes de Meuse", ["Vaudemont", "Othe", "Champougny", "Nancois-sur-Ornain", "Verdun@55", "Brandeville",
                                   "Lion Devant Dun", "Pagny-la-Blanche-Cote", "Letanne", "Socourt", "Houeville", "Barville",
                                   "Circourt sur Mouzon", "Scy-Chazelles"], []),
    ("Côte de Jade", ["La Bernerie-en-Retz", "La Bernerie en Retz", "Saint-Michel-Chef"], []),
    ("Coteaux du Layon", ["Beaulieu sur Layon", "Chaudefonds-sur-Layon", "La Chapelle Saint Florent"], []),
    ("Agenais", ["Ayet", "Penne-d'Agenais", "Nicole"], []),
    ("Charente – Angoumois", ["Voulgezac", "La Couronne", "Montboyer"], []),
    ("Vallée de l'Eure – Vexin", ["Ivry la Bataille", "Guerny", "Ezy sur Eure", "Notre-Dame-de-la-Mer",
                                  "Saint-Germain-de-la-Grange", "Beynes"], []),
    ("Alpes mancelles", ["Saint-Leonard-des-Bois"], []),
    ("Artois – Gohelle", ["Maisnil les Ruitz", "La Comte"], []),
    # Corse
    ("Corse – Ajaccio", ["Vero", "Calcatoggio", "Ajaccio", "Vizzavona", "Bastelica", "Afa"], []),
    ("Corse – Balagne, Cap Corse", ["Nonza", "Barrettali", "Barbaggio", "Saint Florent", "Patrimonio", "Lavatoggio", "Belgodere",
                                    "Palasca"], []),
    ("Corse – Corte, Niolo", ["Calacuccia", "Acquale", "Corte"], []),
    ("Corse – Côte orientale", ["Cervione", "Tox"], []),
    ("Corse – Piana", ["Piana", "Ota"], []),
    # Suisse (no FFVL take-off: points of its own)
    ("Alpes vaudoises – Chablais", [], [[46.359, 7.002], [46.321, 7.068], [46.388, 7.060], [46.319, 6.879], [46.258, 6.889],
                                        [46.351, 6.833]]),
    ("Valais – Verbier", [], [[46.061, 7.355], [46.100, 7.220]]),
    ("Jura vaudois", [], [[46.854, 6.612], [46.773, 6.466], [46.445, 6.176]]),
]


def key(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\bste?\.?\s", lambda m: "sainte " if m.group(0).startswith("ste") else "saint ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def build(raw: list) -> tuple[list, list[str]]:
    by_suid = {str(t["suid"]): t for t in raw}
    takeoffs = ffvl_takeoffs(raw)
    places: dict[tuple[str, str], list] = {}
    for t in takeoffs:
        r = by_suid[t["source_id"]]
        places.setdefault((key(r.get("city")), (r.get("zip") or "")[:2]), []).append([round(t["lat"], 4), round(t["lon"], 4)])
    problems, used = [], {}
    out = []
    for name, communes, own in SECTORS:
        points = [list(p) for p in own]
        for c in communes:
            town, _, dep = c.partition("@")
            found = [(k, v) for k, v in places.items() if k[0] == key(town) and (not dep or k[1] == dep)]
            if not found:
                problems.append(f"{name}: no FFVL take-off in « {c} »")
            for k, v in found:
                if k in used:  # two spellings of one commune in the same sector are fine
                    if used[k] != name:
                        problems.append(f"{name}: « {c} » is already in {used[k]}")
                    continue
                used[k] = name
                points += v
        out.append({"name": name, "points": points})
    return out, problems


def main() -> None:
    if len(sys.argv) > 1:
        raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        from sync_sites import ffvl_file
        raw = ffvl_file()
    sectors, problems = build(raw)
    for p in problems:
        print("!", p)
    body = ",\n".join(f"  {json.dumps(s, ensure_ascii=False, separators=(',', ':'))}" for s in sectors)
    OUT.write_text(
        "// Made by scripts/make_sectors.py from the FFVL file (Licence Ouverte 2.0): edit the sectors there, not here.\n"
        f"export const SECTORS = [\n{body},\n];\n", encoding="utf-8", newline="\n")
    print(f"{len(sectors)} sectors, {sum(len(s['points']) for s in sectors)} points -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
