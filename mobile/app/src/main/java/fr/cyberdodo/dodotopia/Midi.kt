package fr.cyberdodo.dodotopia

import java.io.ByteArrayOutputStream

/** Fichier refusé : pas un MIDI, tronqué, ou sans aucune note jouable. Le message est destiné au journal. */
class MidiIllisible(message: String) : Exception(message)

/** Une note du morceau. Les temps sont en millisecondes depuis le début ; [piste] est l'indice de la piste dans le fichier. */
class NoteMidi(val debutMs: Long, val dureeMs: Int, val hauteur: Int, val piste: Int = 0)

/** Résumé d'une piste, tel que les salons l'échangent (orchestra.track_summary côté PC). */
class PisteMidi(
    val index: Int, val nom: String, val notes: Int,
    val bas: Int, val haut: Int, val moyenne: Double, val percussions: Boolean,
)

class MidiLu(val notes: List<NoteMidi>, val pistes: List<PisteMidi>)

/**
 * Lecture d'un fichier MIDI standard (formats 0 et 1) : notes de toutes les pistes, tempo compris.
 * Le canal 10 (percussions) est écarté des notes, comme sur PC : ses numéros de note ne sont pas des hauteurs.
 */
object Midi {

    private class Evenement(val tick: Long, val debut: Boolean, val cle: Int, val piste: Int)
    private class Tempo(val tick: Long, val microsParNoire: Int)

    private const val CANAL_PERCUSSIONS = 9
    private const val DUREE_SANS_FIN_MS = 200

    fun lire(octets: ByteArray): List<NoteMidi> = analyser(octets).notes

    /**
     * Les notes sans celles des pistes [coupees] (skip_tracks côté PC). Un choix qui ne laisserait plus
     * aucune note est ignoré : mieux vaut jouer tout le morceau que rien.
     */
    fun sansPistes(notes: List<NoteMidi>, coupees: Set<Int>): List<NoteMidi> {
        if (coupees.isEmpty()) return notes
        return notes.filter { it.piste !in coupees }.ifEmpty { notes }
    }

    fun analyser(octets: ByteArray): MidiLu {
        try {
            return decoder(octets)
        } catch (e: IndexOutOfBoundsException) {
            throw MidiIllisible("fichier tronqué")
        }
    }

    private fun decoder(o: ByteArray): MidiLu {
        if (o.size < 14 || texte(o, 0) != "MThd") throw MidiIllisible("en-tête MThd absent")
        val division = entier(o, 12, 2)
        if (division and 0x8000 != 0) throw MidiIllisible("base de temps SMPTE non gérée")
        if (division == 0) throw MidiIllisible("division nulle")

        val evenements = ArrayList<Evenement>()
        val tempos = ArrayList<Tempo>()
        val pistes = ArrayList<PisteMidi>()
        var p = 8 + entier(o, 4, 4)
        var index = 0
        while (p + 8 <= o.size) {
            val taille = entier(o, p + 4, 4)
            if (texte(o, p) == "MTrk") {
                piste(o, p + 8, minOf(p + 8 + taille, o.size), index, evenements, tempos)?.let(pistes::add)
                index++
            }
            p += 8 + taille
        }
        if (evenements.isEmpty()) throw MidiIllisible("aucune note")

        // Tri stable : à tick égal, l'ordre du fichier est gardé (fin de note avant la suivante).
        evenements.sortBy { it.tick }
        tempos.sortBy { it.tick }

        val notes = ArrayList<NoteMidi>()
        val ouvertes = HashMap<Int, ArrayDeque<Evenement>>()
        val debuts = HashMap<Evenement, Long>()
        var iTempo = 0
        var tickRef = 0L
        var microsRef = 0.0
        var microsParNoire = 500_000
        fun millis(tick: Long): Long {
            while (iTempo < tempos.size && tempos[iTempo].tick <= tick) {
                val t = tempos[iTempo++]
                microsRef += (t.tick - tickRef).toDouble() * microsParNoire / division
                tickRef = t.tick
                microsParNoire = t.microsParNoire
            }
            return ((microsRef + (tick - tickRef).toDouble() * microsParNoire / division) / 1000.0).toLong()
        }
        for (e in evenements) {
            val t = millis(e.tick)
            // La clé garde la piste et le canal, pour apparier début et fin.
            val cle = (e.piste shl 16) or e.cle
            if (e.debut) {
                ouvertes.getOrPut(cle) { ArrayDeque() }.addLast(e)
                debuts[e] = t
            } else {
                val debut = ouvertes[cle]?.removeFirstOrNull() ?: continue
                val t0 = debuts.remove(debut)!!
                notes.add(NoteMidi(t0, (t - t0).toInt().coerceAtLeast(1), e.cle and 0x7F, e.piste))
            }
        }
        for ((e, t0) in debuts) notes.add(NoteMidi(t0, DUREE_SANS_FIN_MS, e.cle and 0x7F, e.piste))
        if (notes.isEmpty()) throw MidiIllisible("aucune note")
        notes.sortWith(compareBy({ it.debutMs }, { it.hauteur }))
        return MidiLu(notes, pistes)
    }

    /** Lit une piste ; rend son résumé si elle a des notes (percussions comprises, pour l'affichage des salons). */
    private fun piste(
        o: ByteArray, debut: Int, fin: Int, index: Int,
        evenements: MutableList<Evenement>, tempos: MutableList<Tempo>,
    ): PisteMidi? {
        var p = debut
        var tick = 0L
        var statut = 0
        var nom = ""
        var notes = 0
        var bas = 127
        var haut = 0
        var somme = 0L
        var horsPercussions = false
        fun resume() =
            if (notes == 0) null else PisteMidi(index, nom, notes, bas, haut, somme.toDouble() / notes, !horsPercussions)
        while (p < fin) {
            var delta = 0L
            while (true) {
                val b = o[p++].toInt() and 0xFF
                delta = (delta shl 7) or (b and 0x7F).toLong()
                if (b and 0x80 == 0) break
            }
            tick += delta
            var b = o[p].toInt() and 0xFF
            if (b and 0x80 != 0) {
                statut = b
                p++
            } else if (statut == 0) {
                throw MidiIllisible("octet de statut manquant")
            }
            when {
                statut == 0xFF -> {
                    val type = o[p++].toInt() and 0xFF
                    var taille = 0
                    while (true) {
                        b = o[p++].toInt() and 0xFF
                        taille = (taille shl 7) or (b and 0x7F)
                        if (b and 0x80 == 0) break
                    }
                    if (type == 0x51 && taille == 3) tempos.add(Tempo(tick, entier(o, p, 3).coerceAtLeast(1)))
                    if (type == 0x03 && nom.isEmpty() && p + taille <= fin) {
                        nom = String(o, p, taille, Charsets.ISO_8859_1).filter { it >= ' ' }.trim().take(60)
                    }
                    p += taille
                    if (type == 0x2F) return resume()
                }
                statut == 0xF0 || statut == 0xF7 -> {
                    var taille = 0
                    while (true) {
                        b = o[p++].toInt() and 0xFF
                        taille = (taille shl 7) or (b and 0x7F)
                        if (b and 0x80 == 0) break
                    }
                    p += taille
                }
                else -> {
                    val type = statut and 0xF0
                    val canal = statut and 0x0F
                    val d1 = o[p++].toInt() and 0x7F
                    val d2 = if (type == 0xC0 || type == 0xD0) 0 else o[p++].toInt() and 0x7F
                    if (type == 0x90 && d2 > 0) {
                        notes++
                        bas = minOf(bas, d1); haut = maxOf(haut, d1); somme += d1
                        if (canal != CANAL_PERCUSSIONS) horsPercussions = true
                    }
                    if (canal != CANAL_PERCUSSIONS && (type == 0x90 || type == 0x80)) {
                        // Note On de vélocité 0 = Note Off.
                        evenements.add(Evenement(tick, type == 0x90 && d2 > 0, (canal shl 8) or d1, index))
                    }
                }
            }
        }
        return resume()
    }

    /**
     * Écrit des notes dans un fichier MIDI d'une seule piste (480 ticks par noire, 120 à la noire) :
     * c'est ce qui permet de partager les airs d'exemple dans un salon comme n'importe quel fichier.
     */
    fun ecrire(notes: List<NoteMidi>): ByteArray {
        class Bord(val tick: Long, val debut: Boolean, val hauteur: Int)
        val bords = ArrayList<Bord>()
        for (n in notes) {
            // 500 ms par noire, 480 ticks par noire.
            bords.add(Bord(n.debutMs * 480 / 500, true, n.hauteur))
            bords.add(Bord((n.debutMs + n.dureeMs) * 480 / 500, false, n.hauteur))
        }
        bords.sortWith(compareBy({ it.tick }, { it.debut }))
        val piste = ByteArrayOutputStream()
        fun variable(v: Long) {
            var pile = v and 0x7F
            var reste = v shr 7
            while (reste > 0) {
                pile = (pile shl 8) or ((reste and 0x7F) or 0x80)
                reste = reste shr 7
            }
            while (true) {
                piste.write((pile and 0xFF).toInt())
                if (pile and 0x80 == 0L) break
                pile = pile shr 8
            }
        }
        variable(0); piste.write(byteArrayOf(0xFF.toByte(), 0x51, 0x03, 0x07, 0xA1.toByte(), 0x20))
        var tick = 0L
        for (b in bords) {
            variable(b.tick - tick)
            tick = b.tick
            piste.write(if (b.debut) 0x90 else 0x80)
            piste.write(b.hauteur)
            piste.write(if (b.debut) 96 else 0)
        }
        variable(0); piste.write(byteArrayOf(0xFF.toByte(), 0x2F, 0x00))
        val corps = piste.toByteArray()
        val sortie = ByteArrayOutputStream()
        sortie.write("MThd".toByteArray(Charsets.ISO_8859_1))
        sortie.write(byteArrayOf(0, 0, 0, 6, 0, 0, 0, 1, 0x01, 0xE0.toByte()))
        sortie.write("MTrk".toByteArray(Charsets.ISO_8859_1))
        sortie.write(byteArrayOf((corps.size ushr 24).toByte(), (corps.size ushr 16).toByte(), (corps.size ushr 8).toByte(), corps.size.toByte()))
        sortie.write(corps)
        return sortie.toByteArray()
    }

    private fun texte(o: ByteArray, p: Int) = String(o, p, 4, Charsets.ISO_8859_1)

    private fun entier(o: ByteArray, p: Int, n: Int): Int {
        var v = 0
        for (i in 0 until n) v = (v shl 8) or (o[p + i].toInt() and 0xFF)
        return v
    }
}
