package fr.cyberdodo.dodotopia

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File

/** Lecture et écriture des fichiers MIDI : fichiers fabriqués à la main, puis de vrais fichiers s'il y en a. */
class MidiTest {

    /** Petit assembleur de fichiers MIDI : on écrit les octets qu'on veut voir relus. */
    private class Piste {
        val octets = ByteArrayOutputStream()

        fun delta(ticks: Int): Piste {
            val pile = ArrayList<Int>()
            var v = ticks
            pile.add(v and 0x7F)
            v = v shr 7
            while (v > 0) {
                pile.add((v and 0x7F) or 0x80)
                v = v shr 7
            }
            for (b in pile.reversed()) octets.write(b)
            return this
        }

        fun brut(vararg valeurs: Int): Piste {
            for (v in valeurs) octets.write(v)
            return this
        }

        fun nom(texte: String): Piste {
            val t = texte.toByteArray(Charsets.ISO_8859_1)
            brut(0xFF, 0x03, t.size)
            octets.write(t)
            return this
        }

        fun tempo(microsParNoire: Int) =
            brut(0xFF, 0x51, 0x03, (microsParNoire shr 16) and 0xFF, (microsParNoire shr 8) and 0xFF, microsParNoire and 0xFF)

        fun on(canal: Int, note: Int, velocite: Int = 96) = brut(0x90 or canal, note, velocite)
        fun off(canal: Int, note: Int) = brut(0x80 or canal, note, 0)
        fun fin() = brut(0xFF, 0x2F, 0x00)
    }

    private fun fichier(format: Int, division: Int, vararg pistes: Piste): ByteArray {
        val s = ByteArrayOutputStream()
        s.write("MThd".toByteArray(Charsets.ISO_8859_1))
        s.write(byteArrayOf(0, 0, 0, 6, 0, format.toByte(), 0, pistes.size.toByte(), (division shr 8).toByte(), division.toByte()))
        for (p in pistes) {
            val corps = p.octets.toByteArray()
            s.write("MTrk".toByteArray(Charsets.ISO_8859_1))
            s.write(byteArrayOf((corps.size ushr 24).toByte(), (corps.size ushr 16).toByte(), (corps.size ushr 8).toByte(), corps.size.toByte()))
            s.write(corps)
        }
        return s.toByteArray()
    }

    @Test
    fun lectureSimple() {
        // 480 ticks par noire, tempo par défaut (120 à la noire) : une noire dure 500 ms.
        val piste = Piste()
            .delta(0).on(0, 60).delta(480).off(0, 60)
            .delta(0).on(0, 64).delta(240).off(0, 64)
            .delta(0).fin()
        val notes = Midi.lire(fichier(0, 480, piste))
        assertEquals(2, notes.size)
        assertEquals(0L, notes[0].debutMs)
        assertEquals(500, notes[0].dureeMs)
        assertEquals(60, notes[0].hauteur)
        assertEquals(500L, notes[1].debutMs)
        assertEquals(250, notes[1].dureeMs)
        assertEquals(64, notes[1].hauteur)
    }

    @Test
    fun noteOnDeVelociteNulleEtStatutCourant() {
        // Deuxième et troisième événements sans octet de statut : le précédent (0x90) reste valable.
        val piste = Piste()
            .delta(0).on(0, 60)
            .delta(480).brut(60, 0)
            .delta(0).brut(62, 90)
            .delta(480).brut(62, 0)
            .delta(0).fin()
        val notes = Midi.lire(fichier(0, 480, piste))
        assertEquals(listOf(60, 62), notes.map { it.hauteur })
        assertEquals(listOf(0L, 500L), notes.map { it.debutMs })
        assertEquals(listOf(500, 500), notes.map { it.dureeMs })
    }

    @Test
    fun changementDeTempo() {
        // Piste 0 : 120 à la noire, puis 60 à la noire à partir du tick 480. Les notes sont sur la piste 1.
        val tempos = Piste().delta(0).tempo(500_000).delta(480).tempo(1_000_000).delta(0).fin()
        val notes = Piste()
            .delta(0).on(0, 60).delta(480).off(0, 60)          // 0 à 500 ms
            .delta(0).on(0, 62).delta(480).off(0, 62)          // 500 à 1500 ms : la noire dure maintenant 1 s
            .delta(480).on(0, 64).delta(240).off(0, 64)        // 2500 à 3000 ms
            .delta(0).fin()
        val lu = Midi.analyser(fichier(1, 480, tempos, notes))
        assertEquals(listOf(0L, 500L, 2500L), lu.notes.map { it.debutMs })
        assertEquals(listOf(500, 1000, 500), lu.notes.map { it.dureeMs })
        assertTrue(lu.notes.all { it.piste == 1 })
    }

    @Test
    fun resumeDesPistesEtPercussions() {
        val chef = Piste().delta(0).tempo(500_000).delta(0).fin()
        val melodie = Piste().delta(0).nom("Mélodie")
            .delta(0).on(0, 72).delta(480).off(0, 72)
            .delta(0).on(0, 76).delta(480).off(0, 76)
            .delta(0).fin()
        val basse = Piste().delta(0).nom("Basse")
            .delta(0).on(1, 36).delta(960).off(1, 36)
            .delta(0).fin()
        val batterie = Piste().delta(0).nom("Batterie")
            .delta(0).on(9, 38).delta(120).off(9, 38)
            .delta(360).on(9, 42).delta(120).off(9, 42)
            .delta(0).fin()
        val lu = Midi.analyser(fichier(1, 480, chef, melodie, basse, batterie))

        // La piste sans note n'a pas de résumé ; les indices restent ceux du fichier.
        assertEquals(listOf(1, 2, 3), lu.pistes.map { it.index })
        assertEquals(listOf("Mélodie", "Basse", "Batterie"), lu.pistes.map { it.nom })
        assertEquals(listOf(2, 1, 2), lu.pistes.map { it.notes })
        assertEquals(72, lu.pistes[0].bas)
        assertEquals(76, lu.pistes[0].haut)
        assertEquals(74.0, lu.pistes[0].moyenne, 0.001)
        assertEquals(listOf(false, false, true), lu.pistes.map { it.percussions })

        // Le canal 10 n'est jamais joué comme des hauteurs.
        assertEquals(3, lu.notes.size)
        assertFalse(lu.notes.any { it.piste == 3 })
        assertEquals(setOf(1, 2), lu.notes.map { it.piste }.toSet())
    }

    @Test
    fun couperDesPistes() {
        val notes = listOf(NoteMidi(0, 100, 60, 1), NoteMidi(0, 100, 40, 2), NoteMidi(200, 100, 62, 1))
        assertEquals(3, Midi.sansPistes(notes, emptySet()).size)
        assertEquals(listOf(40), Midi.sansPistes(notes, setOf(1)).map { it.hauteur })
        assertEquals(listOf(60, 62), Midi.sansPistes(notes, setOf(2, 7)).map { it.hauteur })
        // Tout couper ne laisse rien à jouer : le choix est ignoré.
        assertEquals(3, Midi.sansPistes(notes, setOf(1, 2)).size)
    }

    @Test
    fun noteSansFinEtNotesRepetees() {
        val piste = Piste()
            .delta(0).on(0, 60)
            .delta(240).on(0, 60)              // rejouée avant d'être relâchée
            .delta(240).off(0, 60)
            .delta(0).on(0, 67)                // jamais relâchée
            .delta(0).fin()
        val notes = Midi.lire(fichier(0, 480, piste))
        assertEquals(3, notes.size)
        assertEquals(listOf(60, 60, 67), notes.map { it.hauteur })
        assertTrue(notes.all { it.dureeMs > 0 })
    }

    @Test
    fun ecritureRelue() {
        val notes = listOf(
            NoteMidi(0, 450, 60), NoteMidi(500, 225, 64), NoteMidi(500, 225, 67),
            NoteMidi(1250, 1000, 72), NoteMidi(61_000, 300, 48),
        )
        val relues = Midi.analyser(Midi.ecrire(notes))
        assertEquals(1, relues.pistes.size)
        assertEquals(5, relues.pistes[0].notes)
        assertEquals(notes.map { it.hauteur }, relues.notes.map { it.hauteur })
        for ((attendue, lue) in notes.zip(relues.notes)) {
            // 480 ticks pour 500 ms : l'arrondi au tick coûte au plus 2 ms.
            assertTrue(Math.abs(attendue.debutMs - lue.debutMs) <= 2)
            assertTrue(Math.abs(attendue.dureeMs - lue.dureeMs) <= 2)
        }
        // Écrire deux fois le même morceau donne le même fichier : son empreinte l'identifie dans un salon.
        assertTrue(Midi.ecrire(notes).contentEquals(Midi.ecrire(notes)))
    }

    @Test
    fun fichiersRefuses() {
        fun refuse(octets: ByteArray) {
            try {
                Midi.lire(octets)
                fail("fichier accepté")
            } catch (e: MidiIllisible) {
                // attendu
            }
        }
        refuse(ByteArray(0))
        refuse("Ceci n'est pas un fichier MIDI, juste du texte.".toByteArray())
        // Aucune note.
        refuse(fichier(0, 480, Piste().delta(0).tempo(500_000).delta(0).fin()))
        // Base de temps SMPTE.
        refuse(fichier(0, 0xE728, Piste().delta(0).on(0, 60).delta(10).off(0, 60).delta(0).fin()))
        // Tronqué au milieu d'une piste : erreur propre, pas un plantage.
        val entier = fichier(0, 480, Piste().delta(0).on(0, 60).delta(480).off(0, 60).delta(0).on(0, 62).delta(480).off(0, 62).delta(0).fin())
        for (taille in 15 until entier.size - 1) {
            try {
                Midi.lire(entier.copyOf(taille))
            } catch (e: MidiIllisible) {
                // un fichier coupé peut aussi garder assez de notes pour être lu : les deux issues sont bonnes
            }
        }
    }

    // ------------------------------------------------------------------ vrais fichiers (absents : tests ignorés)

    private val telechargements = File("C:/Users/pizzp/Downloads")

    private fun reel(nom: String): ByteArray {
        val f = File(telechargements, nom)
        assumeTrue("fichier de test absent : $nom", f.isFile)
        return f.readBytes()
    }

    /** Les chiffres attendus viennent de mido (la bibliothèque du client PC) sur les mêmes fichiers. */
    private fun commeLePc(nom: String, notes: Int, premierMs: Double, dernierMs: Double, pistes: Map<Int, Int>) {
        val lu = Midi.analyser(reel(nom))
        assertEquals(notes, lu.notes.size)
        assertEquals(premierMs, lu.notes.first().debutMs.toDouble(), 2.0)
        assertEquals(dernierMs, lu.notes.maxOf { it.debutMs }.toDouble(), 2.0)
        assertEquals(pistes, lu.pistes.associate { it.index to it.notes })
    }

    @Test
    fun fichierReelFormat1() = commeLePc(
        "05_-_popular.mid", 2002, 0.0, 202285.8, mapOf(1 to 446, 2 to 1069, 3 to 60, 4 to 425, 5 to 2),
    )

    @Test
    fun fichierReelAvecPercussions() = commeLePc(
        "99-Luftballons-1.mid", 2830, 6623.2, 248245.7,
        mapOf(1 to 493, 2 to 18, 3 to 326, 5 to 290, 6 to 540, 7 to 180, 8 to 757, 9 to 2221, 10 to 212, 11 to 4, 12 to 10),
    )

    @Test
    fun fichierReelFormat0() = commeLePc("A HA.Take on me K.mid", 2870, 7122.8, 223465.5, mapOf(0 to 5767))

    @Test
    fun fichierReelNombreusesPistes() = commeLePc(
        "AUD_DS1419.mid", 978, 2984.4, 47953.1,
        mapOf(2 to 63, 3 to 122, 4 to 65, 5 to 66, 6 to 83, 7 to 128, 8 to 128, 9 to 128, 10 to 41, 11 to 203, 12 to 14, 15 to 72, 16 to 68),
    )

    @Test
    fun tousLesFichiersDuDossier() {
        val fichiers = telechargements.listFiles { f -> f.isFile && f.name.endsWith(".mid", true) && f.length() <= Bibliotheque.TAILLE_MAX }
            ?.sortedBy { it.name }.orEmpty()
        assumeTrue("aucun fichier MIDI dans le dossier de téléchargements", fichiers.isNotEmpty())
        var lus = 0
        for (f in fichiers) {
            val lu = try {
                Midi.analyser(f.readBytes())
            } catch (e: MidiIllisible) {
                continue    // refusé proprement : ce test vérifie qu'aucun fichier ne fait planter la lecture
            }
            lus++
            assertTrue(f.name, lu.notes.isNotEmpty())
            assertTrue(f.name, lu.notes.zipWithNext().all { (a, b) -> a.debutMs <= b.debutMs })
            assertTrue(f.name, lu.notes.all { it.dureeMs > 0 && it.hauteur in 0..127 && it.debutMs >= 0 })
            // Chaque note jouable vient d'une piste résumée, et l'arrangement ne perd pas la durée.
            val resumees = lu.pistes.map { it.index }.toSet()
            assertTrue(f.name, lu.notes.all { it.piste in resumees })
            // Le fichier réécrit sur une piste garde toutes ses notes.
            assertEquals(f.name, lu.notes.size, Midi.lire(Midi.ecrire(lu.notes)).size)
        }
        assertTrue("aucun fichier lisible sur ${fichiers.size}", lus > 0)
        println("MidiTest : $lus fichiers lus sur ${fichiers.size}")
    }
}
