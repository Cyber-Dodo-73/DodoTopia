package fr.cyberdodo.dodotopia

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** La répartition des pistes d'un salon, comparée à orchestra.propose du client PC (reference.py), et les versions. */
class OrchestreTest {

    private val pistes = listOf(
        PisteMidi(0, "Melodie", 300, 60, 84, 72.0, false),
        PisteMidi(1, "Accords", 500, 48, 72, 60.0, false),
        PisteMidi(2, "", 200, 30, 50, 40.5, false),
        PisteMidi(3, "Batterie", 400, 35, 50, 40.0, true),
        PisteMidi(5, "Contrechant", 100, 65, 90, 78.2, false),
    )

    private fun parties(sieges: List<Orchestre.Siege>) = Orchestre.proposer(pistes, sieges).mapValues { it.value.pistes }

    @Test
    fun moinsDeJoueursQueDePistes() {
        // Deux joueurs pour quatre pistes mélodiques : groupes contigus, le registre aigu prend le haut.
        val r = parties(listOf(Orchestre.Siege(1, 48, 84), Orchestre.Siege(2, 48, 72)))
        assertEquals(mapOf(1 to listOf(0, 1, 5), 2 to listOf(2)), r)
    }

    @Test
    fun plusDeJoueursQueDePistes() {
        // Six joueurs : chaque piste est jouée, les pistes sont doublées par les registres voisins.
        val sieges = (1..6).map { Orchestre.Siege(it, 48 + if (it % 2 == 1) 12 else 0, if (it % 2 == 1) 84 else 72) }
        val r = parties(sieges)
        assertEquals(
            mapOf(1 to listOf(5), 3 to listOf(0), 5 to listOf(0), 2 to listOf(1), 4 to listOf(1), 6 to listOf(2)),
            r,
        )
        assertEquals(setOf(0, 1, 2, 5), r.values.flatten().toSet())
    }

    @Test
    fun percussionsEtJoueurSeul() {
        val conga = parties(listOf(Orchestre.Siege(1, 48, 84), Orchestre.Siege(2, 48, 84, percussif = true)))
        assertEquals(mapOf(1 to listOf(0, 1, 2, 5), 2 to listOf(3)), conga)
        assertEquals(mapOf(4 to listOf(0, 1, 2, 5)), parties(listOf(Orchestre.Siege(4, 48, 72))))
        // Rien à répartir : pas de table.
        assertTrue(Orchestre.proposer(emptyList(), listOf(Orchestre.Siege(1, 48, 84))).isEmpty())
        // L'octave reste au choix de l'arrangeur.
        assertTrue(Orchestre.proposer(pistes, listOf(Orchestre.Siege(1, 48, 84))).values.all { it.octave == null })
    }

    @Test
    fun registresDesInstruments() {
        val luth = Orchestre.siege(3, "lute")
        assertEquals(listOf(3, 48, 72), listOf(luth.id, luth.bas, luth.haut))
        assertFalse(luth.percussif)
        assertTrue(Orchestre.siege(1, "conga").percussif)
        // Instrument inconnu (catalogue plus récent que l'appli) : le registre du piano.
        val inconnu = Orchestre.siege(9, "theremin")
        assertEquals(listOf(48, 84), listOf(inconnu.bas, inconnu.haut))
        // Les instruments que l'appli mobile annonce sont connus.
        for (d in Dispositions.toutes) assertFalse(Orchestre.siege(1, d.instrument).percussif)
    }

    @Test
    fun libelleDUnePartie() {
        assertEquals("Melodie + Piste 3", Orchestre.libelle(pistes, listOf(0, 2)) { "Piste $it" })
        assertEquals("", Orchestre.libelle(pistes, emptyList()) { "Piste $it" })
        assertEquals("Piste 8", Orchestre.libelle(pistes, listOf(7)) { "Piste $it" })
    }

    @Test
    fun comparaisonDeVersions() {
        assertTrue(Versions.plusRecente("0.6.1", "0.6.0"))
        assertTrue(Versions.plusRecente("0.10.0", "0.9.9"))
        assertTrue(Versions.plusRecente("1.0", "0.99.99"))
        assertTrue(Versions.plusRecente("v0.7.0", "0.6.0"))
        assertTrue(Versions.plusRecente("0.6.0.1", "0.6.0"))
        assertFalse(Versions.plusRecente("0.6.0", "0.6.0"))
        assertFalse(Versions.plusRecente("0.6", "0.6.0"))
        assertFalse(Versions.plusRecente("0.5.9", "0.6.0"))
        assertFalse(Versions.plusRecente("0.6.0-beta", "0.6.0"))
        // Un numéro illisible ne déclenche jamais une mise à jour.
        assertFalse(Versions.plusRecente("", "0.6.0"))
        assertFalse(Versions.plusRecente("dernière", "0.6.0"))
        assertFalse(Versions.plusRecente("1.x.0", "0.6.0"))
        assertFalse(Versions.plusRecente("-1.0", "0.6.0"))
    }
}
