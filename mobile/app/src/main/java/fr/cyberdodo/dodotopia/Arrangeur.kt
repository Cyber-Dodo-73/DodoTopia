package fr.cyberdodo.dodotopia

import kotlin.math.abs

/**
 * Un clavier du jeu : combien de touches, sur combien de rangées, et quelles notes.
 * Mêmes tables que assets/instruments/layouts.json côté PC. Seule la forme de la gamme compte ici
 * (le morceau est transposé pour tenir dessus) ; les rangées ne servent qu'à poser la grille de calibrage.
 */
class Disposition(
    val id: String,
    val nom: Int,
    val detail: Int,
    val rangees: IntArray,
    val notes: IntArray,
    /** Vrai : on cherche aussi la meilleure tonalité (clavier sans dièses). Faux : seulement l'octave. */
    val autoTonalite: Boolean,
    /** Instrument annoncé aux autres joueurs d'un salon (identifiants du catalogue PC). */
    val instrument: String,
) {
    /** Les rangées comme plages d'indices de notes, de la plus grave à la plus aiguë. */
    val groupes: List<IntRange> = run {
        var debut = 0
        rangees.map { n -> (debut until debut + n).also { debut += n } }
    }
}

object Dispositions {
    private val DO_MAJEUR = intArrayOf(0, 2, 4, 5, 7, 9, 11)

    private fun diatonique(depuis: Int, combien: Int) =
        IntArray(combien) { depuis + 12 * (it / 7) + DO_MAJEUR[it % 7] }

    val toutes = listOf(
        Disposition("15-3", R.string.disp_15_3, R.string.disp_15_3_detail, intArrayOf(5, 5, 5), diatonique(60, 15), true, "lute"),
        Disposition("15-2", R.string.disp_15_2, R.string.disp_15_2_detail, intArrayOf(7, 8), diatonique(60, 15), true, "piano"),
        Disposition("22", R.string.disp_22, R.string.disp_22_detail, intArrayOf(7, 7, 8), diatonique(48, 22), true, "piano"),
        Disposition("37", R.string.disp_37, R.string.disp_37_detail, intArrayOf(12, 12, 13), IntArray(37) { 48 + it }, false, "piano"),
    )

    fun parId(id: String?): Disposition = toutes.firstOrNull { it.id == id } ?: toutes[0]
}

/**
 * Des touches à enfoncer au même instant (indices dans [Disposition.notes]).
 * [durees] : la durée de chaque note en millisecondes du morceau, dans le même ordre que [touches]
 * (null : appuis courts seulement, comme le test des touches).
 */
class Frappe(val tMs: Long, val touches: IntArray, val durees: IntArray? = null)

class Arrangement(
    val frappes: List<Frappe>,
    /** Part des notes (0-100) jouées à leur hauteur exacte, à la transposition près. */
    val couverture: Int,
    val dureeMs: Long,
    /** Transposition appliquée, en demi-tons. */
    val decalage: Int = 0,
    /** Vrai si la mélodie a été suivie et l'accompagnement allégé (arrange.py côté PC). */
    val melodie: Boolean = false,
    /** Notes d'accompagnement laissées de côté par l'arrangeur (sans touche juste, ou au-delà de la polyphonie). */
    val omises: Int = 0,
) {
    /**
     * La suite du morceau à partir de [positionMs], ramenée à zéro : ce qu'il reste à jouer quand on rejoint
     * un salon en marche. La bulle la joue comme un morceau entier, sans connaître la position.
     */
    fun depuis(positionMs: Long): Arrangement {
        if (positionMs <= 0) return this
        val suite = frappes.filter { it.tMs >= positionMs }.map { Frappe(it.tMs - positionMs, it.touches, it.durees) }
        return Arrangement(suite, couverture, (dureeMs - positionMs).coerceAtLeast(0), decalage, melodie, omises)
    }
}

/**
 * Fait tenir un morceau sur un clavier : même logique que choose_shift et fit_notes de core.py.
 * Transposition choisie pour garder le plus de notes justes, notes hors registre repliées d'une octave,
 * altérations absentes ramenées à la touche voisine.
 *
 * Sur un clavier sans dièses, l'arrangeur d'arrange.py passe d'abord (réglage [melodieParDefaut]) : la mélodie
 * est repérée et toujours gardée, ses phrases changent d'octave en entier, et une note d'accompagnement sans
 * touche juste est omise plutôt que remplacée par sa voisine.
 */
object Arrangeur {
    /** Des notes à moins de 12 ms l'une de l'autre forment un accord. */
    private const val FENETRE_ACCORD_MS = 12

    /** Au-delà, les doigts simulés se gênent : on garde la basse et les notes les plus aiguës. */
    private const val MAX_TOUCHES = 6

    private const val POIDS_MELODIE = 3

    /** Silence qui sépare deux phrases de mélodie. */
    private const val SILENCE_PHRASE_MS = 400

    /** Une note plus grave d'une octave sous une mélodie tenue est de l'accompagnement. */
    private const val SOUS_TENUE = 12

    /** Notes à la fois quand l'arrangeur passe (DEFAULT_POLYPHONY côté PC). */
    private const val POLYPHONIE = 4

    /** Écart minimal entre le relâchement d'une touche et son appui suivant (min_gap côté PC). */
    private const val ECART_MIN_MS = 12

    private val DO_MAJEUR = setOf(0, 2, 4, 5, 7, 9, 11)

    /**
     * Réglage « arrangeur » de l'utilisateur, lu par [arranger] quand l'appelant ne précise rien.
     * [Bibliotheque] le relit des préférences à sa création ; il ne s'applique qu'aux claviers sans dièses (mode « auto » du PC).
     */
    @Volatile
    var melodieParDefaut = true

    private class Accord(val tMs: Long, val notes: List<NoteMidi>)

    /** Une note d'accompagnement gardée : hauteur après transposition et durée. */
    private class Voix(val hauteur: Int, val dureeMs: Int)

    /**
     * Décalage en demi-tons (-6..5) qui met le plus de notes sur la gamme de do majeur. Il ne dépend ni de
     * l'instrument ni de l'octave : c'est la tonalité commune d'un salon (choose_common_extra de sync.py).
     */
    fun tonaliteCommune(notes: List<NoteMidi>): Int {
        if (notes.isEmpty()) return 0
        val classes = IntArray(12)
        for (n in notes) classes[n.hauteur % 12]++
        return (-6..5).maxWithOrNull(
            compareBy<Int>({ e -> (0 until 12).sumOf { if (Math.floorMod(it + e, 12) in DO_MAJEUR) classes[it] else 0 } }, { -abs(it) })
        )!!
    }

    /**
     * [tonalite] impose le décalage en demi-tons (salon : le même pour tous, seule l'octave reste libre) ;
     * [octave] ajoute des octaves à la transposition choisie (partie d'orchestre réglée par le chef).
     * La durée rendue est celle des notes reçues : filtrer les pistes avant d'appeler ne doit pas la raccourcir,
     * d'où [dureeMs] pour l'imposer. [melodie] : passer par l'arrangeur (sans effet sur un clavier chromatique).
     */
    fun arranger(
        notes: List<NoteMidi>, d: Disposition,
        tonalite: Int? = null, octave: Int = 0, dureeMs: Long? = null,
        melodie: Boolean = melodieParDefaut,
    ): Arrangement {
        if (notes.isEmpty()) return Arrangement(emptyList(), 0, dureeMs ?: 0)
        val bas = d.notes.first()
        val haut = d.notes.last()
        // Pour chaque écart depuis la note la plus grave : l'indice de la touche la plus proche.
        val touche = IntArray(haut - bas + 1) { ecart ->
            d.notes.indices.minByOrNull { abs(d.notes[it] - bas - ecart) * 2 + if (d.notes[it] - bas > ecart) 1 else 0 }!!
        }
        val dansGamme = BooleanArray(haut - bas + 1).also { for (n in d.notes) it[n - bas] = true }
        val classes = BooleanArray(12).also { for (n in d.notes) it[(n - bas) % 12] = true }
        val extras = when {
            tonalite != null -> tonalite..tonalite
            d.autoTonalite -> -6..5
            else -> 0..0
        }

        var accords = grouper(notes)
        val arrange = melodie && d.autoTonalite
        val decalage: Int
        var omises = 0
        if (arrange) {
            val voix = voixMelodie(accords)
            val poids = IntArray(128)
            for ((a, accord) in accords.withIndex()) {
                for ((i, n) in accord.notes.withIndex()) poids[n.hauteur] += if (i == voix[a]) POIDS_MELODIE else 1
            }
            decalage = decalage(poids, bas, haut, dansGamme, classes, extras) + 12 * octave
            val avant = accords.sumOf { it.notes.size }
            accords = alleger(accords, voix, decalage, bas, haut, dansGamme)
            omises = avant - accords.sumOf { it.notes.size }
        } else {
            val histogramme = IntArray(128)
            for (n in notes) histogramme[n.hauteur]++
            decalage = decalage(histogramme, bas, haut, dansGamme, classes, extras) + 12 * octave
        }

        val frappes = ArrayList<Frappe>()
        var exactes = 0
        var total = 0
        for (accord in accords) {
            val touches = ArrayList<Int>()
            val durees = ArrayList<Int>()
            for (n in accord.notes) {
                total++
                var m = n.hauteur + decalage
                val dansRegistre = m in bas..haut
                while (m < bas) m += 12
                while (m > haut) m -= 12
                if (dansRegistre && dansGamme[m - bas]) exactes++
                val k = touche[m - bas]
                val deja = touches.indexOf(k)
                if (deja < 0) {
                    touches.add(k)
                    durees.add(n.dureeMs)
                } else if (n.dureeMs > durees[deja]) {
                    durees[deja] = n.dureeMs
                }
            }
            val ordre = touches.indices.sortedBy { touches[it] }
            val gardes = if (ordre.size > MAX_TOUCHES) listOf(ordre[0]) + ordre.takeLast(MAX_TOUCHES - 1) else ordre
            frappes.add(Frappe(accord.tMs, IntArray(gardes.size) { touches[gardes[it]] }, IntArray(gardes.size) { durees[gardes[it]] }))
        }
        val fin = dureeMs ?: notes.maxOf { it.debutMs + it.dureeMs }
        val couverture = if (total == 0) 0 else (100L * exactes / total).toInt()
        return Arrangement(frappes, couverture, fin, decalage, arrange, omises)
    }

    /** Les notes regroupées en accords, sans deux fois la même hauteur dans un accord. */
    private fun grouper(notes: List<NoteMidi>): List<Accord> {
        val accords = ArrayList<Accord>()
        var i = 0
        while (i < notes.size) {
            val t = notes[i].debutMs
            val ensemble = ArrayList<NoteMidi>()
            while (i < notes.size && notes[i].debutMs - t <= FENETRE_ACCORD_MS) {
                val n = notes[i++]
                if (ensemble.none { it.hauteur == n.hauteur }) ensemble.add(n)
            }
            accords.add(Accord(t, ensemble))
        }
        return accords
    }

    /**
     * La transposition qui garde le plus de notes justes (choose_shift). [poids] : pour chaque hauteur MIDI,
     * le nombre de notes (la mélodie compte triple quand l'arrangeur passe). À score égal : la tonalité puis
     * l'octave les plus proches de l'original, puis le décalage le plus haut, comme sur PC.
     */
    private fun decalage(poids: IntArray, bas: Int, haut: Int, dansGamme: BooleanArray, classes: BooleanArray, extras: IntRange): Int {
        var choisi = 0
        var meilleur: LongArray? = null
        for (oct in -4..4) {
            for (extra in extras) {
                val s = 12 * oct + extra
                var score = 0L
                for (h in 0 until 128) {
                    if (poids[h] == 0) continue
                    val m = h + s
                    val points = when {
                        m in bas..haut -> if (dansGamme[m - bas]) 2 else 1
                        classes[Math.floorMod(m - bas, 12)] -> 1
                        else -> 0
                    }
                    score += points.toLong() * poids[h]
                }
                val candidat = longArrayOf(score, -abs(extra).toLong(), -abs(oct).toLong(), s.toLong())
                if (meilleur == null || plusGrand(candidat, meilleur)) {
                    meilleur = candidat
                    choisi = s
                }
            }
        }
        return choisi
    }

    /**
     * Pour chaque accord, l'indice de sa note de mélodie, ou -1 (melody_flags) : la voix supérieure de chaque
     * attaque, sauf quand l'attaque est nettement sous une note de mélodie encore tenue.
     */
    private fun voixMelodie(accords: List<Accord>): IntArray {
        val voix = IntArray(accords.size) { -1 }
        var tenueJusqua = -1L
        var tenue: Int? = null
        for ((a, accord) in accords.withIndex()) {
            var haut = 0
            for (i in accord.notes.indices) if (accord.notes[i].hauteur > accord.notes[haut].hauteur) haut = i
            val n = accord.notes[haut]
            if (tenue != null && accord.tMs < tenueJusqua - 1 && n.hauteur <= tenue - SOUS_TENUE) continue
            voix[a] = haut
            tenue = n.hauteur
            tenueJusqua = accord.tMs + n.dureeMs
        }
        return voix
    }

    private fun replier(hauteur: Int, bas: Int, haut: Int): Int {
        var m = hauteur
        while (m < bas) m += 12
        while (m > haut) m -= 12
        return m
    }

    /**
     * Le cœur d'arrange.py : chaque phrase de mélodie prend l'octave où elle tient le mieux, l'accompagnement
     * passe sous la mélodie, ne garde que ses notes justes et respecte la polyphonie. Les hauteurs rendues
     * sont avant transposition : [decalage] les remet en place.
     */
    private fun alleger(accords: List<Accord>, voix: IntArray, decalage: Int, bas: Int, haut: Int, dansGamme: BooleanArray): List<Accord> {
        fun juste(m: Int) = m in bas..haut && dansGamme[m - bas]

        // 1. Mélodie : une octave par phrase (coupure sur un silence).
        val melodie = HashMap<Int, Int>()
        val phrases = ArrayList<ArrayList<Int>>()
        var phrase = ArrayList<Int>()
        var fin: Long? = null
        for ((a, accord) in accords.withIndex()) {
            if (voix[a] < 0) continue
            if (phrase.isNotEmpty() && fin != null && accord.tMs - fin > SILENCE_PHRASE_MS) {
                phrases.add(phrase)
                phrase = ArrayList()
            }
            phrase.add(a)
            fin = maxOf(fin ?: accord.tMs, accord.tMs + accord.notes[voix[a]].dureeMs)
        }
        if (phrase.isNotEmpty()) phrases.add(phrase)
        for (ph in phrases) {
            val hauteurs = ph.map { accords[it].notes[voix[it]].hauteur + decalage }
            var k = 0
            var meilleur: LongArray? = null
            for (essai in -3..3) {
                val justes = hauteurs.count { juste(it + 12 * essai) }
                val dedans = hauteurs.count { it + 12 * essai in bas..haut }
                val candidat = longArrayOf(justes.toLong(), dedans.toLong(), -abs(essai).toLong())
                if (meilleur == null || plusGrand(candidat, meilleur)) {
                    meilleur = candidat
                    k = essai
                }
            }
            // Une note encore hors registre après le déplacement de la phrase : repli individuel.
            for ((rang, a) in ph.withIndex()) melodie[a] = replier(hauteurs[rang] + 12 * k, bas, haut)
        }

        // 2. Accompagnement : sous la mélodie, touches justes seulement, polyphonie respectée.
        val sortie = ArrayList<Accord>()
        val recent = HashMap<Int, Long>()    // hauteur jouée -> fin de la dernière note de mélodie dessus
        for ((a, accord) in accords.withIndex()) {
            val f = voix[a]
            val mel = melodie[a]
            if (mel != null) recent[mel] = accord.tMs + accord.notes[f].dureeMs
            val accompagnement = ArrayList<Voix>()
            for ((i, n) in accord.notes.withIndex()) {
                if (i == f) continue
                var m = replier(n.hauteur + decalage, bas, haut)
                if (mel != null) {
                    while (m > mel && m - 12 >= bas) m -= 12
                    if (m >= mel) continue
                }
                if (!dansGamme[m - bas]) continue      // pas de touche juste : omise plutôt que jouée à côté
                val finMelodie = recent[m]
                if (finMelodie != null && accord.tMs < finMelodie + ECART_MIN_MS) continue
                accompagnement.add(Voix(m, n.dureeMs))
            }
            var uniques = accompagnement.sortedBy { it.hauteur }.distinctBy { it.hauteur }.filter { it.hauteur != mel }
            val place = POLYPHONIE - if (mel != null) 1 else 0
            if (uniques.size > place) {
                // La basse d'abord, puis les notes les plus longues (les tenues de l'accord).
                uniques = if (place > 0) {
                    (uniques.take(1) + uniques.drop(1).sortedByDescending { it.dureeMs }.take(place - 1)).sortedBy { it.hauteur }
                } else {
                    emptyList()
                }
            }
            val jouees = ArrayList<NoteMidi>()
            for (v in uniques) jouees.add(NoteMidi(accord.tMs, v.dureeMs, v.hauteur - decalage))
            if (mel != null) jouees.add(NoteMidi(accord.tMs, accord.notes[f].dureeMs, mel - decalage))
            if (jouees.isNotEmpty()) sortie.add(Accord(accord.tMs, jouees))
        }
        return sortie
    }

    private fun plusGrand(a: LongArray, b: LongArray): Boolean {
        for (i in a.indices) if (a[i] != b[i]) return a[i] > b[i]
        return false
    }
}
