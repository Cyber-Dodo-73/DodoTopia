package fr.cyberdodo.dodotopia

/**
 * L'Orchestre d'un salon : le chef répartit les pistes du fichier MIDI entre les joueurs, la piste la plus
 * aiguë au registre le plus aigu. Mêmes calculs que orchestra.py côté PC ; rien ici ne touche au réseau.
 */
object Orchestre {

    /** Un joueur à servir : son numéro de siège et le registre de son instrument. */
    class Siege(val id: Int, val bas: Int, val haut: Int, val percussif: Boolean = false)

    /** La partie d'un joueur : ses pistes, et l'octave imposée par le chef (null : choisie par l'arrangeur). */
    class Partie(val pistes: List<Int>, val octave: Int? = null)

    private class Registre(val bas: Int, val haut: Int, val percussif: Boolean = false)

    private val PIANO = Registre(48, 84)
    private val LUTH = Registre(48, 72)
    private val AIGU = Registre(60, 84)

    /**
     * Registre de chaque instrument du catalogue PC, d'après sa disposition par défaut
     * (assets/instruments : « lute-15-3row » do3-do5, « diatonic-15 » do4-do6, piano do3-do6).
     */
    private val REGISTRES = mapOf(
        "piano" to PIANO, "harp" to PIANO,
        "lute" to LUTH, "recorder" to LUTH, "xiao" to LUTH, "concertina" to LUTH, "lyre" to LUTH, "violin" to LUTH,
        "cello" to LUTH, "saxophone" to LUTH, "steel-tongue-drum" to LUTH, "ocarina" to LUTH,
        "wooden-bass" to AIGU, "bagpipe" to AIGU, "mbira" to AIGU,
        "xylophone" to Registre(60, 72),
        "conga" to Registre(48, 84, true), "cajon" to Registre(60, 84, true),
    )

    /** Le siège d'un joueur d'après l'instrument qu'il annonce ; registre du piano s'il est inconnu (seat_register). */
    fun siege(id: Int, instrument: String): Siege {
        val r = REGISTRES[instrument] ?: PIANO
        return Siege(id, r.bas, r.haut, r.percussif)
    }

    /** Découpe [pistes] (déjà triées) en [n] groupes contigus aux nombres de notes équilibrés. */
    private fun partager(pistes: List<PisteMidi>, n: Int): List<List<PisteMidi>> {
        val total = pistes.sumOf { it.notes }
        val groupes = ArrayList<List<PisteMidi>>()
        var courant = ArrayList<PisteMidi>()
        var cumul = 0
        for ((i, p) in pistes.withIndex()) {
            courant.add(p)
            cumul += p.notes
            val groupesRestants = n - groupes.size - 1
            val pistesRestantes = pistes.size - i - 1
            if (groupesRestants > 0 && (cumul >= total.toDouble() * (groupes.size + 1) / n || pistesRestantes == groupesRestants)) {
                groupes.add(courant)
                courant = ArrayList()
            }
        }
        if (courant.isNotEmpty()) groupes.add(courant)
        while (groupes.size < n) groupes.add(emptyList())
        return groupes
    }

    /**
     * Répartition automatique (orchestra.propose). Chaque piste mélodique est jouée par au moins un siège
     * quand il y a assez de joueurs ; s'il y a plus de joueurs que de pistes, les pistes sont doublées par
     * les joueurs de registre voisin. Rend une table vide si le morceau n'a aucune piste.
     */
    fun proposer(pistes: List<PisteMidi>, sieges: List<Siege>): Map<Int, Partie> {
        val melodiques = pistes.filter { !it.percussions && it.notes > 0 }.sortedByDescending { it.moyenne }
        val percussions = pistes.filter { it.percussions && it.notes > 0 }.map { it.index }
        if (melodiques.isEmpty() && percussions.isEmpty()) return emptyMap()
        val accordes = sieges.filter { !it.percussif }.sortedByDescending { (it.bas + it.haut) / 2.0 }
        val frappes = sieges.filter { it.percussif }
        val sortie = LinkedHashMap<Int, Partie>()
        if (melodiques.isNotEmpty() && accordes.isNotEmpty()) {
            val s = accordes.size
            val t = melodiques.size
            if (s >= t) {
                for ((j, siege) in accordes.withIndex()) {
                    val k = if (s > 1) arrondi(j * (t - 1).toDouble() / (s - 1)) else 0
                    sortie[siege.id] = Partie(listOf(melodiques[k].index))
                }
            } else {
                for ((siege, groupe) in accordes.zip(partager(melodiques, s))) {
                    sortie[siege.id] = Partie(groupe.map { it.index }.sorted())
                }
            }
        }
        for (siege in frappes) {
            val choix = percussions.ifEmpty { melodiques.lastOrNull()?.let { listOf(it.index) } ?: emptyList() }
            sortie[siege.id] = Partie(choix.sorted())
        }
        for (siege in accordes) {
            if (siege.id !in sortie) sortie[siege.id] = Partie(melodiques.map { it.index }.ifEmpty { percussions })
        }
        return sortie
    }

    /** round() de Python : la moitié va au nombre pair, pour tomber sur la même piste que le PC. */
    private fun arrondi(x: Double): Int = Math.rint(x).toInt()

    /** « Mélodie + Basse » : les noms des pistes d'une partie ; [sansNom] donne « Piste 3 » pour une piste sans nom. */
    fun libelle(pistes: List<PisteMidi>, partie: List<Int>, sansNom: (Int) -> String): String {
        val noms = pistes.associate { it.index to it.nom.trim() }
        return partie.joinToString(" + ") { i -> noms[i].orEmpty().ifEmpty { sansNom(i + 1) } }
    }
}
