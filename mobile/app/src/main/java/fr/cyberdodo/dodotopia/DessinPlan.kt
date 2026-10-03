package fr.cyberdodo.dodotopia

import kotlin.math.pow

/**
 * Les 126 couleurs de l'outil de peinture d'Heartopia. Sans Android, pour être essayé hors appareil.
 *
 * Un bouton « palette », à gauche des 16 pastilles, les remplace par les nuances d'une famille : 2 colonnes × 5
 * lignes (6 nuances pour la famille du noir), lues de gauche à droite puis de haut en bas. Les familles sont des
 * pages qu'on parcourt avec deux flèches, dans l'ordre noir, rouge, orange… rose (SHADE_FAMILIES et PAGES de draw.py).
 */
object Nuancier {

    /** Pastille de la palette principale qui représente chaque famille, dans l'ordre des pages du jeu. */
    val FAMILLES = intArrayOf(0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)

    const val COLONNES = 2
    const val LIGNES = 5

    /** Les nuances telles que la version PC les affiche (SHADE_FAMILIES de draw.py, lues sur des captures PC). */
    private val SUR_PC = arrayOf(
        intArrayOf(0x051616, 0x414545, 0x808282, 0xBEBFBF, 0xFEFFFF, 0xF9F6EC),
        intArrayOf(0xCF354D, 0xEE6F72, 0xA6263D, 0xF5ACA6, 0xC98483, 0xA35D5E, 0x69313B, 0xE7D5D5, 0xC0ACAB, 0x755E5E),
        intArrayOf(0xE95E2B, 0xF98358, 0xAB4226, 0xFEBA9F, 0xD9937C, 0xAF6C58, 0x753B31, 0xE9D5D0, 0xC1ACA6, 0x755E59),
        intArrayOf(0xF49E16, 0xFEAE3B, 0xB16F16, 0xFECE92, 0xDAA76D, 0xB3814B, 0x795126, 0xF5E4CE, 0xCDBCA9, 0x806F5E),
        intArrayOf(0xEDCA16, 0xF9D838, 0xB39416, 0xFAE791, 0xD3BE6F, 0xAB954B, 0x756326, 0xEEE7C7, 0xC6BFA2, 0x787259),
        intArrayOf(0xA8BC16, 0xB6C931, 0x758616, 0xD8DF93, 0xADB76D, 0x85914B, 0x535E2B, 0xE6E9C7, 0xBCC2A3, 0x6E745D),
        intArrayOf(0x05A25D, 0x41B97B, 0x057447, 0x9CDAAD, 0x76B28B, 0x4F8969, 0x245640, 0xC3E0CC, 0x9DB7A6, 0x53695D),
        intArrayOf(0x058781, 0x05ABA0, 0x056966, 0x7ECDC2, 0x55A49C, 0x2B7E78, 0x054B4B, 0xBEE0DA, 0x98B7B2, 0x4E6B66),
        intArrayOf(0x05729C, 0x0599BA, 0x055878, 0x79BBCA, 0x5193A5, 0x246D7F, 0x05495B, 0xC6DDE2, 0x9EB5BA, 0x4F676F),
        intArrayOf(0x055EA6, 0x2B83C1, 0x054782, 0x83A8C9, 0x5D80A1, 0x365B7F, 0x193B56, 0xC1CDD5, 0x9BA6B0, 0x4C5967),
        intArrayOf(0x534DA1, 0x7577BD, 0x3E387E, 0xA2A0C7, 0x787AA1, 0x55567E, 0x333555, 0xC9CAD5, 0xA2A3B0, 0x565869),
        intArrayOf(0x813D8B, 0xA167A9, 0x602B6C, 0xB89BB9, 0x907395, 0x6C4D73, 0x432E4B, 0xCFC9D1, 0xABA1AC, 0x605665),
        intArrayOf(0xAD356F, 0xCF6B8F, 0x862658, 0xD9A1B4, 0xB47A8C, 0x8B5367, 0x60354B, 0xE4D5DA, 0xBCADB1, 0x725E66),
    )

    /** Nombre de nuances : 126. */
    val TAILLE = SUR_PC.sumOf { it.size }

    /** Page (0 = noir … 12 = rose) et rang dans la page de chaque nuance. */
    val PAGE = IntArray(TAILLE)
    val RANG = IntArray(TAILLE)

    /**
     * Couleur de chaque nuance sur l'écran du jeu mobile (0xRRGGBB). Le jeu mobile affiche les couleurs de la
     * version PC élevées à la puissance 2,2 : vérifié sur les 16 pastilles principales (capture du 2026-10-03,
     * écart de 3 au plus par composante), supposé pour les autres nuances, qui n'ont pas été relevées sur mobile.
     */
    val COULEURS = IntArray(TAILLE)

    /** Pastille de la palette principale qui donne la même couleur, ou -1 : c'est la 2e nuance de chaque famille, et pour le noir, le gris, le blanc et le crème. */
    val PRINCIPALE = IntArray(TAILLE) { -1 }

    /** Nuance de chacune des 16 pastilles de la palette principale. */
    val DE_PRINCIPALE = IntArray(16)

    /** Les deux tons des rayures de la toile vide (capture mobile du 2026-10-03). */
    val TOILE_VIDE = intArrayOf(0xF1E9DA, 0xFFF5E9)

    val BLANC: Int
    val CREME: Int

    init {
        var k = 0
        for (page in SUR_PC.indices) for (rang in SUR_PC[page].indices) {
            PAGE[k] = page
            RANG[k] = rang
            val c = SUR_PC[page][rang]
            COULEURS[k] = (mobile((c shr 16) and 0xFF) shl 16) or (mobile((c shr 8) and 0xFF) shl 8) or mobile(c and 0xFF)
            k++
        }
        // Le blanc, le gris et le crème de la palette principale sont des nuances de la famille du noir.
        for ((rang, pastille) in listOf(0 to 0, 4 to 1, 2 to 2, 5 to 3)) PRINCIPALE[rang] = pastille
        for (n in 0 until TAILLE) if (PAGE[n] > 0 && RANG[n] == 1) PRINCIPALE[n] = FAMILLES[PAGE[n]]
        for (n in 0 until TAILLE) if (PRINCIPALE[n] >= 0) DE_PRINCIPALE[PRINCIPALE[n]] = n
        BLANC = DE_PRINCIPALE[1]
        CREME = DE_PRINCIPALE[3]
    }

    private fun mobile(composante: Int): Int = ((composante / 255.0).pow(2.2) * 255.0 + 0.5).toInt()

    /** Nombre de nuances de la page [page]. */
    fun taille(page: Int): Int = SUR_PC[page].size

    /** La nuance de rang [rang] dans la page [page]. */
    fun nuance(page: Int, rang: Int): Int {
        var k = 0
        for (p in 0 until page) k += SUR_PC[p].size
        return k + rang
    }

    /** Distance « redmean » entre deux couleurs : plus proche de l'œil qu'un écart RGB brut, sans passer par CIELAB. */
    fun ecart(a: Int, b: Int): Long {
        val ar = (a shr 16) and 0xFF
        val br = (b shr 16) and 0xFF
        val moyen = (ar + br) / 2
        val dr = (ar - br).toLong()
        val dv = (((a shr 8) and 0xFF) - ((b shr 8) and 0xFF)).toLong()
        val db = ((a and 0xFF) - (b and 0xFF)).toLong()
        return (512 + moyen) * dr * dr / 256 + 4 * dv * dv + (767 - moyen) * db * db / 256
    }

    /** Carré de la distance RGB brute, pour comparer une couleur lue à l'écran avec celle qu'on attend. */
    fun ecartBrut(a: Int, b: Int): Int {
        val dr = ((a shr 16) and 0xFF) - ((b shr 16) and 0xFF)
        val dv = ((a shr 8) and 0xFF) - ((b shr 8) and 0xFF)
        val db = (a and 0xFF) - (b and 0xFF)
        return dr * dr + dv * dv + db * db
    }

    /** La nuance la plus proche de [couleur] parmi [parmi] (toutes si null). */
    fun plusProche(couleur: Int, parmi: IntArray? = null): Int {
        var meilleur = 0
        var mini = Long.MAX_VALUE
        if (parmi == null) {
            for (k in 0 until TAILLE) {
                val d = ecart(couleur, COULEURS[k])
                if (d < mini) {
                    mini = d
                    meilleur = k
                }
            }
        } else {
            for (k in parmi) {
                val d = ecart(couleur, COULEURS[k])
                if (d < mini) {
                    mini = d
                    meilleur = k
                }
            }
        }
        return meilleur
    }

    /** Une couleur trop proche des rayures de la toile vide ne se vérifie pas à l'écran (comme `_checkable` de draw.py). */
    fun verifiable(k: Int): Boolean = TOILE_VIDE.all { ecartBrut(COULEURS[k], it) > 40 * 40 }
}

/**
 * Ce qu'il faut tracer pour peindre une image : les traits du crayon et, en mode contours, les zones à remplir au
 * pot de peinture (`plan_outline` de draw.py). Sans Android, pour être essayé hors appareil.
 */
object PlanDessin {

    /** Un trait droit, horizontal ou vertical, de la case (x0, y0) à la case (x1, y1). */
    class Segment(val x0: Int, val y0: Int, val x1: Int, val y1: Int) {
        /** Nombre de cases traversées après la première. */
        val longueur: Int get() = kotlin.math.abs(x1 - x0) + kotlin.math.abs(y1 - y0)

        /** Indices des cases peintes par ce trait, sur une grille de [largeur] cases de large. */
        fun cases(largeur: Int): IntArray {
            val n = longueur + 1
            val dx = Integer.signum(x1 - x0)
            val dy = Integer.signum(y1 - y0)
            return IntArray(n) { (y0 + it * dy) * largeur + x0 + it * dx }
        }
    }

    /**
     * Les traits qui couvrent exactement les cases de [masque]. Chaque case part dans le sens où sa suite de
     * cases est la plus longue : une bande verticale se peint en quelques traits verticaux plutôt qu'en une
     * multitude de traits courts. Le sens change d'une rangée (ou d'une colonne) à l'autre pour ne pas
     * retraverser la toile.
     */
    fun segments(masque: BooleanArray, largeur: Int, hauteur: Int): List<Segment> {
        val enLargeur = IntArray(masque.size)
        val enHauteur = IntArray(masque.size)
        for (y in 0 until hauteur) {
            var x = 0
            while (x < largeur) {
                if (!masque[y * largeur + x]) {
                    x++
                    continue
                }
                val debut = x
                while (x < largeur && masque[y * largeur + x]) x++
                for (i in debut until x) enLargeur[y * largeur + i] = x - debut
            }
        }
        for (x in 0 until largeur) {
            var y = 0
            while (y < hauteur) {
                if (!masque[y * largeur + x]) {
                    y++
                    continue
                }
                val debut = y
                while (y < hauteur && masque[y * largeur + x]) y++
                for (j in debut until y) enHauteur[j * largeur + x] = y - debut
            }
        }
        fun vertical(n: Int) = masque[n] && enHauteur[n] > enLargeur[n]
        fun horizontal(n: Int) = masque[n] && enHauteur[n] <= enLargeur[n]

        val sortie = ArrayList<Segment>()
        var versLaDroite = true
        for (y in 0 until hauteur) {
            val rangee = ArrayList<Segment>()
            var x = 0
            while (x < largeur) {
                if (!horizontal(y * largeur + x)) {
                    x++
                    continue
                }
                val debut = x
                while (x < largeur && horizontal(y * largeur + x)) x++
                rangee.add(Segment(debut, y, x - 1, y))
            }
            if (rangee.isEmpty()) continue
            if (versLaDroite) sortie.addAll(rangee) else sortie.addAll(rangee.asReversed().map { Segment(it.x1, it.y0, it.x0, it.y1) })
            versLaDroite = !versLaDroite
        }
        var versLeBas = true
        for (x in 0 until largeur) {
            val colonne = ArrayList<Segment>()
            var y = 0
            while (y < hauteur) {
                if (!vertical(y * largeur + x)) {
                    y++
                    continue
                }
                val debut = y
                while (y < hauteur && vertical(y * largeur + x)) y++
                colonne.add(Segment(x, debut, x, y - 1))
            }
            if (colonne.isEmpty()) continue
            if (versLeBas) sortie.addAll(colonne) else sortie.addAll(colonne.asReversed().map { Segment(it.x0, it.y1, it.x1, it.y0) })
            versLeBas = !versLeBas
        }
        return sortie
    }

    /** Une zone à remplir au pot : la case où appuyer (la plus loin du bord de la zone) et toutes ses cases. */
    class Zone(val graine: Int, val cases: IntArray)

    /** Mode contours : par couleur, les cases à peindre au crayon et les zones à remplir au pot. */
    class Contours(val crayon: Map<Int, BooleanArray>, val zones: Map<Int, List<Zone>>)

    /**
     * Mode contours (`plan_outline` de draw.py). [cases] : la couleur de chaque case, négative pour une case qui
     * reste vide. [fond] : couleur déjà versée sur toute la toile par un premier coup de pot, ou -1.
     *
     * Règle du mur unique : entre deux couleurs voisines, seule la moins présente (à égalité : celle du plus
     * grand numéro) peint sa frontière ; face au vide ou au fond, chacune peint la sienne ; le fond ne peint rien.
     * Une fois tous les contours tracés, chaque case encore à remplir n'a pour voisines (8 directions) que des
     * cases de sa couleur ou des cases déjà peintes : le pot ne peut pas déborder, qu'il passe par les coins ou non.
     * Une zone de moins de [minimum] cases est peinte au crayon : un coup de pot coûte plus qu'il ne rapporte.
     */
    fun contours(cases: ByteArray, largeur: Int, hauteur: Int, fond: Int, minimum: Int): Contours {
        val n = largeur * hauteur
        val compte = HashMap<Int, Int>()
        for (c in cases) if (c >= 0) compte[c.toInt()] = (compte[c.toInt()] ?: 0) + 1
        fun peintFace(k: Int, voisine: Int): Boolean {
            if (voisine < 0 || voisine == fond) return true
            val a = compte[voisine] ?: 0
            val b = compte[k] ?: 0
            return a > b || (a == b && voisine > k)
        }

        val contour = BooleanArray(n)
        for (y in 0 until hauteur) for (x in 0 until largeur) {
            val i = y * largeur + x
            val k = cases[i].toInt()
            if (k < 0 || k == fond) continue
            boucle@ for (vy in maxOf(0, y - 1)..minOf(hauteur - 1, y + 1)) for (vx in maxOf(0, x - 1)..minOf(largeur - 1, x + 1)) {
                val voisine = cases[vy * largeur + vx].toInt()
                if (voisine != k && peintFace(k, voisine)) {
                    contour[i] = true
                    break@boucle
                }
            }
        }

        val crayon = HashMap<Int, BooleanArray>()
        val zones = HashMap<Int, List<Zone>>()
        val vue = BooleanArray(n)
        val pile = IntArray(n)
        for (depart in 0 until n) {
            val k = cases[depart].toInt()
            if (k < 0 || k == fond) continue
            val masque = crayon.getOrPut(k) { BooleanArray(n) }
            if (contour[depart]) {
                masque[depart] = true
                continue
            }
            if (vue[depart]) continue
            // L'intérieur d'une zone : les cases de la même couleur hors contour, voisines par un côté.
            val zone = ArrayList<Int>()
            var haut = 0
            pile[haut++] = depart
            vue[depart] = true
            while (haut > 0) {
                val c = pile[--haut]
                zone.add(c)
                val cx = c % largeur
                val cy = c / largeur
                for (d in 0 until 4) {
                    val vx = cx + DX[d]
                    val vy = cy + DY[d]
                    if (vx < 0 || vy < 0 || vx >= largeur || vy >= hauteur) continue
                    val v = vy * largeur + vx
                    if (!vue[v] && !contour[v] && cases[v].toInt() == k) {
                        vue[v] = true
                        pile[haut++] = v
                    }
                }
            }
            if (zone.size < minimum) {
                for (c in zone) masque[c] = true
            } else {
                val liste = zone.toIntArray()
                (zones.getOrPut(k) { ArrayList() } as ArrayList<Zone>).add(Zone(graine(liste, largeur, hauteur), liste))
            }
        }
        return Contours(crayon, zones)
    }

    private val DX = intArrayOf(-1, 1, 0, 0)
    private val DY = intArrayOf(0, 0, -1, 1)

    /** La case d'une zone la plus éloignée de son bord (à égalité : la plus proche de son centre), pour l'appui du pot. */
    fun graine(zone: IntArray, largeur: Int, hauteur: Int): Int {
        val dedans = HashSet<Int>(zone.size * 2)
        for (c in zone) dedans.add(c)
        val distance = HashMap<Int, Int>(zone.size * 2)
        val file = ArrayList<Int>(zone.size)
        for (c in zone) {
            val cx = c % largeur
            val cy = c / largeur
            for (d in 0 until 4) {
                val vx = cx + DX[d]
                val vy = cy + DY[d]
                if (vx < 0 || vy < 0 || vx >= largeur || vy >= hauteur || (vy * largeur + vx) !in dedans) {
                    distance[c] = 0
                    file.add(c)
                    break
                }
            }
        }
        var tete = 0
        while (tete < file.size) {
            val c = file[tete++]
            val cx = c % largeur
            val cy = c / largeur
            for (d in 0 until 4) {
                val vx = cx + DX[d]
                val vy = cy + DY[d]
                if (vx < 0 || vy < 0 || vx >= largeur || vy >= hauteur) continue
                val v = vy * largeur + vx
                if (v in dedans && v !in distance) {
                    distance[v] = distance[c]!! + 1
                    file.add(v)
                }
            }
        }
        var x0 = largeur
        var x1 = 0
        var y0 = hauteur
        var y1 = 0
        for (c in zone) {
            x0 = minOf(x0, c % largeur); x1 = maxOf(x1, c % largeur)
            y0 = minOf(y0, c / largeur); y1 = maxOf(y1, c / largeur)
        }
        val mx = (x0 + x1) / 2f
        val my = (y0 + y1) / 2f
        var meilleure = zone[0]
        var profondeur = -1
        var ecart = Float.MAX_VALUE
        for (c in zone) {
            val p = distance[c] ?: 0
            val e = (c % largeur - mx) * (c % largeur - mx) + (c / largeur - my) * (c / largeur - my)
            if (p > profondeur || (p == profondeur && e < ecart)) {
                meilleure = c
                profondeur = p
                ecart = e
            }
        }
        return meilleure
    }
}
