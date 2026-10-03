package fr.cyberdodo.dodotopia

import kotlin.math.hypot

/**
 * La boucle de la cuisine : ce qu'il faut faire de chaque capture lue par [CuisineVue]. Sans Android, pour être
 * rejouée hors appareil sur les captures d'une vraie session.
 *
 * Elle agit sur ce qu'elle voit, comme `_loop_multi` de cook.py sur PC :
 *  - un anneau vert → un appui, répété tant que l'anneau reste (un appui peut ne pas prendre) ;
 *  - des gants → le plat est récupéré ;
 *  - une poêle → un appui ouvre le menu des recettes, puis la tuile récente et le bouton Cuisiner ;
 *  - un dialogue en bas de l'écran (plat amélioré) → un appui dessus le referme ;
 *  - un écran inconnu (boîte aux lettres, inventaire, autre menu du jeu) → rien, puis l'arrêt au bout d'une minute.
 *
 * Une seule cuisinière par défaut : la première bulle prise (la plus proche du milieu de l'écran, là où se tient
 * le personnage) est suivie d'une capture à l'autre, et les bulles des cuisinières voisines sont ignorées.
 * Avec [plusieurs], toutes les bulles d'une zone plus large sont servies. Piège relevé sur PC : toucher une bulle
 * fait marcher le personnage jusqu'à sa cuisinière, la caméra le suit et toutes les bulles glissent ensemble ;
 * pendant ce temps, une bulle n'est touchée que si elle n'a pas bougé depuis la capture d'avant.
 *
 * [intervalleMs] : temps entre deux captures. [journal] reçoit une ligne quand ce que montre l'écran change.
 */
class CuisineBoucle(private val plusieurs: Boolean, private val intervalleMs: Long, private val journal: (String) -> Unit) {

    /** Pourquoi la cuisine s'arrête d'elle-même. */
    enum class Fin { INGREDIENTS, FEU_BLOQUE, PERDUE }

    /** Un appui à envoyer, [delaiMs] après la décision. */
    class Appui(val x: Float, val y: Float, val delaiMs: Long = 0)

    class Decision(val appuis: List<Appui>, val fin: Fin? = null)

    var plats = 0; private set
    var feux = 0; private set

    private var dernierResume = ""
    private var precedentes: List<CuisineVue.Bulle> = emptyList()
    private var precedentesA = 0L

    /** Dernière fois où l'écran montrait quelque chose de connu (bulle, menu, dialogue) ; 0 avant la première capture. */
    private var vuA = 0L
    private var appuisDansLeVide = 0
    private var dernierVide = 0L
    private var perdue = 0
    private var essaisMenu = 0
    private var cuissonsAvant = 0
    private var dernierMenu = 0L
    private var dernierDialogue = 0L
    private var dernierLancement = 0L
    private var dernierGants = 0L
    private var dernierFeu = 0L
    private var feuX = 0f
    private var feuY = 0f
    private var feuxDeSuite = 0

    /** Dernier appui sur une bulle : la caméra peut bouger dans les secondes qui suivent. */
    private var dernierAppuiBulle = 0L

    /** Où se trouvait la bulle de notre cuisinière à la dernière capture où on l'a vue (0 = pas encore choisie). */
    private var bulleX = 0f
    private var bulleY = 0f

    /** Ce qu'il faut faire de la capture [v], lue à l'instant [maintenant] (millisecondes d'une horloge qui ne recule pas). */
    fun decider(v: CuisineVue.Lecture, maintenant: Long): Decision {
        if (vuA == 0L) vuA = maintenant
        val resume = when {
            v.menu -> "menu des recettes"
            v.dialogue -> "dialogue"
            v.bulles.isEmpty() -> "rien"
            else -> v.bulles.joinToString(" ") { "${it.type} (${it.x.toInt()}, ${it.y.toInt()})" }
        }
        if (resume != dernierResume) {
            dernierResume = resume
            journal(resume)
        }
        if (v.menu) {
            vuA = maintenant
            appuisDansLeVide = 0
            precedentes = emptyList()
            if (maintenant - dernierMenu < ATTENTE_MENU_MS) return RIEN
            // Le menu qui revient sans que rien de nouveau ne cuise : le bouton Cuisiner n'a pas pris (plus d'ingrédients ?).
            if (++essaisMenu > ESSAIS_MENU) return Decision(emptyList(), Fin.INGREDIENTS)
            dernierMenu = maintenant
            return Decision(
                listOf(
                    Appui(TUILE_X * v.largeur, TUILE_Y * v.hauteur),
                    // Le bouton trouvé par sa couleur (écran qui n'est pas en 16:9), sinon sa place relevée en 16:9.
                    if (v.cuisinerX >= 0) Appui(v.cuisinerX, v.cuisinerY, ATTENTE_TUILE_MS)
                    else Appui(CUISINER_X * v.largeur, CUISINER_Y * v.hauteur, ATTENTE_TUILE_MS),
                )
            )
        }
        if (v.dialogue) {
            // Plat amélioré : le jeu attend qu'on touche l'écran. La boîte de dialogue ne recouvre aucune bulle.
            vuA = maintenant
            appuisDansLeVide = 0
            precedentes = emptyList()
            if (maintenant - dernierDialogue < ATTENTE_DIALOGUE_MS) return RIEN
            dernierDialogue = maintenant
            return appui(CuisineVue.DIALOGUE_CX * v.largeur, CuisineVue.DIALOGUE_CY * v.hauteur)
        }

        val bulles = if (plusieurs) immobiles(v, maintenant) else laNotre(v)
        precedentes = v.bulles
        precedentesA = maintenant
        if (v.bulles.isNotEmpty()) {
            vuA = maintenant
            appuisDansLeVide = 0
        }
        // Une cuisson de plus qu'avant le dernier lancement : le bouton Cuisiner a bien pris.
        val cuissons = (if (plusieurs) v.bulles else bulles).count { it.type == CuisineVue.Type.CUISSON || it.type == CuisineVue.Type.FEU }
        if (cuissons > cuissonsAvant) essaisMenu = 0
        if (cuissons < cuissonsAvant) cuissonsAvant = cuissons

        // 1. Le feu : rien n'attend moins.
        val anneaux = bulles.filter { it.type == CuisineVue.Type.FEU }
        if (anneaux.isNotEmpty()) {
            val recent = dernierFeu > 0 && maintenant - dernierFeu < MEME_FEU_MS
            // Deux anneaux : pas deux fois de suite le même.
            val b = if (recent && anneaux.size > 1) anneaux.maxByOrNull { hypot(it.x - feuX, it.y - feuY) }!! else anneaux[0]
            val encore = recent && hypot(b.x - feuX, b.y - feuY) < v.largeur * MEME_BULLE
            // Le jeu met un instant à retirer l'anneau après un appui réussi.
            if (encore && maintenant - dernierFeu < ATTENTE_ANNEAU_MS) return RIEN
            feuxDeSuite = if (recent) feuxDeSuite + 1 else 1
            if (feuxDeSuite > FEUX_DE_SUITE) return Decision(emptyList(), Fin.FEU_BLOQUE)
            // Un nouvel appui sur le même anneau n'est pas un second feu.
            if (!encore) feux++
            dernierFeu = maintenant
            feuX = b.x
            feuY = b.y
            return surBulle(b, maintenant)
        }
        // 2. Un plat prêt. La bulle « gants » reste affichée un instant après l'appui : on ne la retouche pas tout de suite.
        val gants = bulles.firstOrNull { it.type == CuisineVue.Type.GANTS }
        if (gants != null) {
            if (dernierGants > 0 && maintenant - dernierGants < ATTENTE_GANTS_MS) return RIEN
            dernierGants = maintenant
            plats++
            journal("plat $plats récupéré")
            return surBulle(gants, maintenant)
        }
        // 3. Une cuisinière au repos : sa bulle ouvre le menu des recettes, traité à la capture suivante.
        val poele = bulles.firstOrNull { it.type == CuisineVue.Type.POELE }
        if (poele != null) {
            if (dernierGants > 0 && maintenant - dernierGants < ATTENTE_APRES_GANTS_MS) return RIEN
            if (dernierLancement > 0 && maintenant - dernierLancement < ATTENTE_MENU_MS) return RIEN
            dernierLancement = maintenant
            cuissonsAvant = cuissons
            return surBulle(poele, maintenant)
        }
        if (v.bulles.isNotEmpty()) return RIEN

        // 4. Rien de connu à l'écran : une animation, une fenêtre du jeu, ou le joueur est parti ailleurs.
        val vide = maintenant - vuA
        if (vide > PERDU_MS) return Decision(emptyList(), Fin.PERDUE)
        // Deux appuis au plus, là où était la bulle : assez pour refermer une animation, trop peu pour faire des
        // dégâts dans une fenêtre inconnue (boîte aux lettres, inventaire…).
        if (bulleX > 0f && vide > VIDE_AVANT_APPUI_MS && appuisDansLeVide < APPUIS_DANS_LE_VIDE && maintenant - dernierVide > VIDE_AVANT_APPUI_MS) {
            appuisDansLeVide++
            dernierVide = maintenant
            return appui(bulleX, bulleY)
        }
        return RIEN
    }

    /** Une seule cuisinière : la bulle la plus proche de la dernière place de la nôtre (ou du milieu de l'écran, la première fois). */
    private fun laNotre(v: CuisineVue.Lecture): List<CuisineVue.Bulle> {
        val suivie = bulleX > 0f
        val ax = if (suivie) bulleX else v.largeur * 0.5f
        val ay = if (suivie) bulleY else v.hauteur * 0.45f
        val rayon = if (suivie) v.largeur * RAYON_SUIVI else Float.MAX_VALUE
        val b = v.bulles.filter { hypot(it.x - ax, it.y - ay) <= rayon }.minByOrNull { hypot(it.x - ax, it.y - ay) }
        if (b == null) {
            // Notre bulle est introuvable alors que d'autres sont là (caméra déplacée) : on la rechoisira près du milieu.
            if (suivie && v.bulles.isNotEmpty() && ++perdue >= CAPTURES_AVANT_OUBLI) {
                journal("bulle perdue, nouvelle recherche")
                bulleX = 0f
                bulleY = 0f
                perdue = 0
            }
            return emptyList()
        }
        // La caméra suit le personnage : la bulle glisse un peu d'une capture à l'autre, on la suit.
        bulleX = b.x
        bulleY = b.y
        perdue = 0
        return listOf(b)
    }

    /**
     * Plusieurs cuisinières : toutes les bulles, sauf, tant que la caméra peut bouger (quelques secondes après un
     * appui sur une bulle), celles qui ont changé de place ou d'icône depuis la capture d'avant.
     */
    private fun immobiles(v: CuisineVue.Lecture, maintenant: Long): List<CuisineVue.Bulle> {
        v.bulles.firstOrNull()?.let { bulleX = it.x; bulleY = it.y }
        if (dernierAppuiBulle == 0L || maintenant - dernierAppuiBulle > CAMERA_MS) return v.bulles
        if (maintenant - precedentesA > 2 * intervalleMs) return emptyList()
        val tolerance = v.largeur * IMMOBILE
        return v.bulles.filter { b -> precedentes.any { it.type == b.type && hypot(it.x - b.x, it.y - b.y) <= tolerance } }
    }

    private fun surBulle(b: CuisineVue.Bulle, maintenant: Long): Decision {
        dernierAppuiBulle = maintenant
        return appui(b.x, b.y)
    }

    private fun appui(x: Float, y: Float) = Decision(listOf(Appui(x, y)))

    companion object {
        private val RIEN = Decision(emptyList())

        /** La bulle suivie est cherchée dans ce rayon autour de sa dernière place (fraction de la largeur d'écran). */
        private const val RAYON_SUIVI = 0.11f
        private const val CAPTURES_AVANT_OUBLI = 8

        /** Deux lectures à moins de 3 % de la largeur d'écran l'une de l'autre montrent la même bulle. */
        private const val MEME_BULLE = 0.03f

        /** Une bulle qui a bougé de plus de 0,8 % de la largeur d'écran entre deux captures glisse avec la caméra. */
        private const val IMMOBILE = 0.008f

        /** Relevé sur PC : la caméra ne bouge que dans les 4,5 s qui suivent un appui sur une bulle. */
        private const val CAMERA_MS = 4500L
        private const val ATTENTE_ANNEAU_MS = 700L
        private const val MEME_FEU_MS = 3000L

        /** Comme sur PC : douze appuis de suite sur un anneau qui ne part pas, et on arrête. */
        private const val FEUX_DE_SUITE = 12
        private const val ATTENTE_GANTS_MS = 1500L
        private const val ATTENTE_APRES_GANTS_MS = 1000L
        private const val ATTENTE_MENU_MS = 2500L
        private const val ATTENTE_TUILE_MS = 500L
        private const val ATTENTE_DIALOGUE_MS = 1000L
        private const val ESSAIS_MENU = 3
        private const val VIDE_AVANT_APPUI_MS = 3000L
        private const val APPUIS_DANS_LE_VIDE = 2

        /** Plus rien de connu à l'écran pendant une minute : le joueur est parti, la cuisine s'arrête. */
        private const val PERDU_MS = 60_000L

        /** Menu des recettes : première tuile (« Utilisation récente ») et bouton Cuisiner, en fractions de l'écran. */
        private const val TUILE_X = 0.11f
        private const val TUILE_Y = 0.258f
        private const val CUISINER_X = 0.7325f
        private const val CUISINER_Y = 0.907f
    }
}
