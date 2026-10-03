package fr.cyberdodo.dodotopia

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min

/**
 * Ce que la cuisine reconnaît sur une capture d'écran. Pur calcul sur les pixels, sans Android : le même code
 * est rejoué hors appareil sur des captures du jeu (75 captures d'une vraie session, 1600×900, le 2026-10-03).
 *
 * Une bulle de cuisinière est un disque sombre qui porte une icône :
 *  - poêle blanche : cuisinière au repos, un appui ouvre le menu des recettes ;
 *  - gants blancs : plat prêt, un appui le récupère ;
 *  - spatule blanche dans un anneau vert : il faut ajuster le feu, vite ;
 *  - minuteur jaune pâle : le plat cuit, rien à faire.
 * Les icônes blanches sont reconnues par leur forme (comme cook.py sur PC), plus par leur nombre de pixels :
 * les bulles des autres joueurs (amitié, carte, tope-là) ont la même taille et la même couleur.
 */
object CuisineVue {

    enum class Type { POELE, GANTS, FEU, CUISSON }

    /** Une bulle reconnue : son centre à l'écran et la ressemblance avec son modèle (1 = identique). */
    class Bulle(val type: Type, val x: Float, val y: Float, val score: Float)

    class Lecture(
        /** Menu des recettes ouvert (il couvre tout l'écran). */
        val menu: Boolean,
        /** Boîte de dialogue en bas de l'écran : « Super ! On dirait que … est encore plus savoureux », plat amélioré. */
        val dialogue: Boolean,
        val bulles: List<Bulle>,
        val largeur: Int,
        val hauteur: Int,
        /** Centre du bouton Cuisiner trouvé dans le menu des recettes (pixels), ou -1 s'il n'a pas été cherché. */
        val cuisinerX: Float = -1f,
        val cuisinerY: Float = -1f,
    )

    /** Côté de la grille qui décrit la forme d'une icône. */
    const val GRILLE = 12

    /**
     * Les trois icônes blanches : part de blanc (0 à 9) dans chaque case d'une grille 12 × 12 tendue sur
     * l'icône, et rapport largeur / hauteur. Relevées sur les captures c20 (poêle), c19 (gants), c13 (spatule).
     */
    private class Modele(val type: Type, val rapport: Float, lignes: String) {
        val cases = FloatArray(GRILLE * GRILLE) { (lignes[it] - '0') / 9f }
    }

    private val MODELES = arrayOf(
        Modele(
            Type.POELE, 1.52f,
            "000000000016" + "000000000062" + "017000000220" + "136000000300" + "459430153000" + "925510353000" +
                "500000000000" + "100000000000" + "025555555510" + "059999999920" + "029999999900" + "008999999600",
        ),
        Modele(
            Type.GANTS, 1.12f,
            "003983000310" + "019997028993" + "048342089999" + "066000399999" + "063230899999" + "033297999996" +
                "656089999994" + "798069999992" + "189159999970" + "019059999940" + "008101589910" + "000000006600",
        ),
        Modele(
            Type.FEU, 1.02f,
            "000000000188" + "000000001782" + "000000004610" + "000000014000" + "000540140000" + "017687600000" +
                "176079710000" + "880371950000" + "873711930000" + "289228500000" + "017685000000" + "002840000000",
        ),
    )

    /** Ressemblance minimale entre une icône et son modèle. Relevé : les vraies icônes dépassent 0,8, les autres bulles restent sous 0,45. */
    private const val SEUIL_FORME = 0.6f

    /** Zone où chercher les bulles, en fractions de l'écran : gauche, droite, haut, bas. Autour : les boutons du jeu. */
    private val ZONE = floatArrayOf(0.30f, 0.80f, 0.12f, 0.75f)
    private val ZONE_LARGE = floatArrayOf(0.12f, 0.88f, 0.10f, 0.82f)

    fun zone(large: Boolean): FloatArray = if (large) ZONE_LARGE else ZONE

    /** Points des bords de l'écran où le menu des recettes est orange. */
    private val MENU_X = floatArrayOf(0.02f, 0.5f, 0.98f, 0.5f, 0.02f, 0.98f, 0.985f, 0.4f, 0.6f)
    private val MENU_Y = floatArrayOf(0.5f, 0.03f, 0.5f, 0.985f, 0.1f, 0.1f, 0.9f, 0.985f, 0.03f)

    /** Points du bouton Cuisiner, bleu-vert : la boîte aux lettres du jeu a le même fond orange, mais pas ce bouton. */
    private val BOUTON_X = floatArrayOf(0.68f, 0.7325f, 0.79f)
    private val BOUTON_Y = floatArrayOf(0.907f, 0.89f, 0.907f)

    /** Recherche du bouton par sa couleur : assez de points bleu-vert pour ne pas prendre une icône pour lui. */
    private const val BOUTON_POINTS_MIN = 12

    /**
     * Boîte de dialogue du bas de l'écran, gris très clair (231, 233, 231) : elle va de 22 % à 78 % de la largeur
     * et de 80 % à 95 % de la hauteur (écran 16:9). On la reconnaît sur deux lignes sans texte, au-dessus et
     * au-dessous de ses deux lignes de texte.
     */
    private val DIALOGUE_Y = floatArrayOf(0.818f, 0.932f)
    private const val DIALOGUE_POINTS = 9

    /** Centre de la boîte de dialogue : un appui dessus la referme. */
    const val DIALOGUE_CX = 0.5f
    const val DIALOGUE_CY = 0.885f

    private const val VERT = 0
    private const val JAUNE = 1
    private const val BLANC = 2

    private fun classe(c: Int): Int {
        val r = (c shr 16) and 0xFF
        val v = (c shr 8) and 0xFF
        val b = c and 0xFF
        return when {
            // Du vert vif (0,240,16) au vert-jaune (96,208,16) : l'anneau change de teinte quand le temps s'écoule.
            v > 150 && b < 70 && v - r > 80 -> VERT
            r >= 244 && v in 226..250 && b in 136..164 -> JAUNE
            r >= 236 && v >= 236 && b >= 236 -> BLANC
            else -> -1
        }
    }

    /** [pixels] : l'écran entier, ligne par ligne (0xRRGGBB, l'octet de poids fort est ignoré). */
    fun lire(pixels: IntArray, l: Int, h: Int, large: Boolean): Lecture {
        fun point(fx: Float, fy: Float) = pixels[(fy * h).toInt().coerceIn(0, h - 1) * l + (fx * l).toInt().coerceIn(0, l - 1)]

        var orange = 0
        for (i in MENU_X.indices) {
            val c = point(MENU_X[i], MENU_Y[i])
            val r = (c shr 16) and 0xFF
            val v = (c shr 8) and 0xFF
            val b = c and 0xFF
            if (r > 215 && v in 111..189 && b < 110) orange++
        }
        fun bleuVert(c: Int): Boolean {
            val r = (c shr 16) and 0xFF
            val v = (c shr 8) and 0xFF
            val b = c and 0xFF
            return r < 80 && v in 110..200 && b in 100..190 && v - r > 70
        }
        var bouton = 0
        for (i in BOUTON_X.indices) if (bleuVert(point(BOUTON_X[i], BOUTON_Y[i]))) bouton++
        if (orange >= 6 && bouton >= 2) return Lecture(true, false, emptyList(), l, h)
        if (orange >= 6) {
            // Écran plus allongé que le 16:9 des relevés : le bouton Cuisiner n'est pas aux fractions attendues.
            // On le cherche par sa couleur dans le bas de l'écran ; son centre est la médiane des points trouvés.
            val xs = ArrayList<Int>()
            val ys = ArrayList<Int>()
            val pas = (h / 90).coerceAtLeast(2)
            var y = (h * 0.78f).toInt()
            while (y < (h * 0.98f).toInt()) {
                var x = (l * 0.35f).toInt()
                while (x < (l * 0.98f).toInt()) {
                    if (bleuVert(pixels[y * l + x])) {
                        xs.add(x)
                        ys.add(y)
                    }
                    x += pas
                }
                y += pas
            }
            if (xs.size >= BOUTON_POINTS_MIN) {
                xs.sort()
                ys.sort()
                return Lecture(true, false, emptyList(), l, h, xs[xs.size / 2].toFloat(), ys[ys.size / 2].toFloat())
            }
        }

        var clair = 0
        for (fy in DIALOGUE_Y) for (i in 0 until DIALOGUE_POINTS) {
            val c = point(0.34f + 0.32f * i / (DIALOGUE_POINTS - 1), fy)
            val r = (c shr 16) and 0xFF
            val v = (c shr 8) and 0xFF
            val b = c and 0xFF
            if (r in 220..242 && v in 220..242 && b in 220..242 && abs(r - b) <= 8) clair++
        }
        val dialogue = clair >= 2 * DIALOGUE_POINTS - 3

        val z = zone(large)
        val x0 = (l * z[0]).toInt()
        val y0 = (h * z[2]).toInt()
        // Cases d'un deux-centième de la largeur d'écran (8 px en 1600) : les seuils suivent la taille de l'écran.
        val case = (l / 200).coerceAtLeast(4)
        val gl = ((l * z[1]).toInt() - x0) / case
        val gh = ((h * z[3]).toInt() - y0) / case
        val grilles = Array(3) { IntArray(gl * gh) }
        for (gy in 0 until gh) for (dy in 0 until case) {
            val ligne = (y0 + gy * case + dy) * l + x0
            for (x in 0 until gl * case) {
                val k = classe(pixels[ligne + x])
                if (k >= 0) grilles[k][gy * gl + x / case]++
            }
        }

        val bulles = ArrayList<Bulle>()
        val marque = IntArray(gl * gh)
        val pile = IntArray(gl * gh)
        // Plus petit amas qui compte : 100 pixels sur un écran de 1600 px de large.
        val minimum = (100L * l * l / (1600 * 1600)).toInt().coerceAtLeast(30)
        // L'anneau vert d'abord : la spatule qu'il entoure ne doit pas donner une seconde bulle.
        for (k in intArrayOf(VERT, BLANC, JAUNE)) {
            val grille = grilles[k]
            java.util.Arrays.fill(marque, 0)
            var numero = 0
            for (depart in grille.indices) {
                if (grille[depart] == 0 || marque[depart] != 0) continue
                // Un amas : les cases voisines (8 directions) qui portent cette couleur.
                numero++
                var haut = 0
                pile[haut++] = depart
                marque[depart] = numero
                var n = 0
                var i0 = gl
                var i1 = 0
                var j0 = gh
                var j1 = 0
                while (haut > 0) {
                    val c = pile[--haut]
                    val ci = c % gl
                    val cj = c / gl
                    n += grille[c]
                    i0 = min(i0, ci); i1 = max(i1, ci); j0 = min(j0, cj); j1 = max(j1, cj)
                    for (dj in -1..1) for (di in -1..1) {
                        val vi = ci + di
                        val vj = cj + dj
                        if (vi < 0 || vj < 0 || vi >= gl || vj >= gh) continue
                        val v = vj * gl + vi
                        if (grille[v] != 0 && marque[v] == 0) {
                            marque[v] = numero
                            pile[haut++] = v
                        }
                    }
                }
                // Une bulle tient dans 7,5 % de la largeur d'écran : au-delà, c'est un texte, un panneau, un décor.
                if (n < minimum || (i1 - i0 + 1) * case > l * 0.085f || (j1 - j0 + 1) * case > l * 0.085f) continue
                val b = bulle(pixels, l, k, marque, numero, gl, case, x0, y0, i0, i1, j0, j1) ?: continue
                // Deux lectures du même endroit (anneau + spatule) : la première trouvée reste.
                if (bulles.none { hypot(it.x - b.x, it.y - b.y) < l * 0.03f }) bulles.add(b)
            }
        }
        return Lecture(false, dialogue, bulles, l, h)
    }

    /** Regarde de près l'amas [numero] de couleur [k] : ses bords au pixel, sa forme, et ce que c'est (ou null). */
    private fun bulle(
        pixels: IntArray, l: Int, k: Int, marque: IntArray, numero: Int, gl: Int, case: Int,
        x0: Int, y0: Int, i0: Int, i1: Int, j0: Int, j1: Int,
    ): Bulle? {
        var gauche = Int.MAX_VALUE
        var droite = -1
        var hautPx = Int.MAX_VALUE
        var bas = -1
        for (j in j0..j1) for (i in i0..i1) {
            if (marque[j * gl + i] != numero) continue
            for (dy in 0 until case) {
                val y = y0 + j * case + dy
                for (dx in 0 until case) {
                    val x = x0 + i * case + dx
                    if (classe(pixels[y * l + x]) != k) continue
                    if (x < gauche) gauche = x
                    if (x > droite) droite = x
                    if (y < hautPx) hautPx = y
                    if (y > bas) bas = y
                }
            }
        }
        if (droite < 0) return null
        val largeur = droite - gauche + 1
        val hauteur = bas - hautPx + 1
        val forme = forme(pixels, l, k, gauche, hautPx, droite, bas)
        val cx = (gauche + droite) / 2f
        val cy = (hautPx + bas) / 2f
        val rapport = largeur.toFloat() / hauteur
        // Le milieu de la forme (4 × 4 cases sur 12 × 12) : vide pour un anneau ou un minuteur.
        var milieu = 0f
        for (j in 4..7) for (i in 4..7) milieu += forme[j * GRILLE + i]
        milieu /= 16f
        return when (k) {
            VERT -> {
                // Anneau de 79 px en 1600 : un rond fin, vide jusqu'aux six dixièmes de son rayon. Une flèche ou une
                // salade vertes ont de la couleur plus près du centre.
                val rond = largeur > l * 0.035f && hauteur > l * 0.035f && rapport in 0.8f..1.25f
                var dedans = 0f
                var cases = 0
                for (j in 0 until GRILLE) for (i in 0 until GRILLE) {
                    if (hypot(i + 0.5f - GRILLE / 2f, j + 0.5f - GRILLE / 2f) < 0.6f * GRILLE / 2f) {
                        dedans += forme[j * GRILLE + i]
                        cases++
                    }
                }
                if (rond && dedans / cases < 0.04f) Bulle(Type.FEU, cx, cy, 1f) else null
            }
            JAUNE -> {
                // Minuteur de 48 × 56 px en 1600 : un rond creux surmonté d'un bouton.
                val rond = largeur > l * 0.02f && largeur < l * 0.045f && rapport in 0.68f..1.05f
                if (rond && milieu < 0.12f) Bulle(Type.CUISSON, cx, cy, 1f) else null
            }
            else -> {
                if (largeur < l * 0.016f || largeur > l * 0.045f || hauteur < l * 0.011f || hauteur > l * 0.045f) return null
                var meilleur: Modele? = null
                var score = 0f
                for (m in MODELES) {
                    if (abs(ln(rapport / m.rapport)) > 0.25f) continue
                    var commun = 0f
                    var total = 0f
                    for (n in forme.indices) {
                        commun += min(forme[n], m.cases[n])
                        total += max(forme[n], m.cases[n])
                    }
                    val s = if (total > 0f) commun / total else 0f
                    if (s > score) {
                        score = s
                        meilleur = m
                    }
                }
                if (meilleur != null && score >= SEUIL_FORME) Bulle(meilleur.type, cx, cy, score) else null
            }
        }
    }

    /**
     * La forme de ce qui est de couleur [k] dans un rectangle : la part de cette couleur (0 à 1) dans chaque case
     * d'une grille 12 × 12 tendue sur le rectangle. Indépendante de la taille de l'écran.
     */
    private fun forme(pixels: IntArray, l: Int, k: Int, gauche: Int, haut: Int, droite: Int, bas: Int): FloatArray {
        val largeur = droite - gauche + 1
        val hauteur = bas - haut + 1
        val forme = FloatArray(GRILLE * GRILLE)
        val aire = IntArray(GRILLE * GRILLE)
        for (y in haut..bas) for (x in gauche..droite) {
            val n = (y - haut) * GRILLE / hauteur * GRILLE + (x - gauche) * GRILLE / largeur
            aire[n]++
            if (classe(pixels[y * l + x]) == k) forme[n]++
        }
        for (n in forme.indices) if (aire[n] > 0) forme[n] /= aire[n]
        return forme
    }

    /** La forme d'un amas blanc en chiffres 0 à 9, comme dans [MODELES] : sert à relever un nouveau modèle hors appareil. */
    fun releverForme(pixels: IntArray, l: Int, gauche: Int, haut: Int, droite: Int, bas: Int): String =
        forme(pixels, l, BLANC, gauche, haut, droite, bas).joinToString("") { (it * 9f + 0.5f).toInt().toString() }

    /** Comme [releverForme], pour l'amas blanc qui entoure un point : son rectangle est cherché dans un carré de côté 2 × [rayon]. */
    fun releverAutour(pixels: IntArray, l: Int, cx: Int, cy: Int, rayon: Int): String {
        var gauche = Int.MAX_VALUE
        var droite = -1
        var haut = Int.MAX_VALUE
        var bas = -1
        for (y in cy - rayon..cy + rayon) for (x in cx - rayon..cx + rayon) {
            if (classe(pixels[y * l + x]) != BLANC) continue
            if (x < gauche) gauche = x
            if (x > droite) droite = x
            if (y < haut) haut = y
            if (y > bas) bas = y
        }
        return "${droite - gauche + 1}x${bas - haut + 1} " + releverForme(pixels, l, gauche, haut, droite, bas)
    }
}
