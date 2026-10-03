package fr.cyberdodo.dodotopia

import android.app.AlertDialog
import android.content.Intent
import android.text.InputFilter
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.io.IOException
import java.net.URLEncoder
import java.util.Locale

/**
 * Le bandeau du compte, en haut de l'accueil : invitation à se connecter avec Discord, code à recopier
 * pendant la connexion, puis le nom du compte. Le même bouton existe sur l'écran de bienvenue.
 */
class BandeauCompte(private val a: AppCompatActivity) {
    private val titre = a.findViewById<TextView>(R.id.compteTitre)
    private val texte = a.findViewById<TextView>(R.id.compteTexte)
    private val code = a.findViewById<TextView>(R.id.compteCode)
    private val bouton = a.findViewById<TextView>(R.id.compteBouton)
    private val lien = a.findViewById<TextView>(R.id.compteLien)
    private val bienvenue = a.findViewById<TextView>(R.id.bienvenueDiscord)
    private val bienvenueTexte = a.findViewById<TextView>(R.id.bienvenueDiscordTexte)

    init {
        Compte.charger(a)
        Compte.utilisateur.observe(a) { afficher() }
        Connexion.etat.observe(a) { afficher() }
        bienvenue.setOnClickListener { Connexion.demarrer(a) }
    }

    private fun afficher() {
        val u = Compte.utilisateur.value
        val e = Connexion.etat.value ?: Connexion.Etat(false)
        code.visibility = View.GONE
        when {
            u != null -> {
                titre.text = a.getString(R.string.compte_connecte, u.nom)
                texte.visibility = View.GONE
                bouton.visibility = View.GONE
                lien.visibility = View.VISIBLE
                lien.setText(R.string.compte_deconnexion)
                lien.setOnClickListener {
                    Salon.quitter()
                    Compte.deconnecter(a)
                }
            }
            e.enCours -> {
                titre.setText(R.string.compte_attente_titre)
                texte.visibility = View.VISIBLE
                texte.setText(R.string.compte_attente_texte)
                if (e.code != null) {
                    code.visibility = View.VISIBLE
                    code.text = e.code
                }
                bouton.visibility = if (e.adresse != null) View.VISIBLE else View.GONE
                bouton.setText(R.string.compte_rouvrir)
                bouton.setOnClickListener { e.adresse?.let { Connexion.ouvrir(a, it) } }
                lien.visibility = View.VISIBLE
                lien.setText(R.string.annuler)
                lien.setOnClickListener { Connexion.annuler() }
            }
            else -> {
                titre.setText(R.string.compte_invite_titre)
                texte.visibility = View.VISIBLE
                texte.text = e.erreur ?: a.getString(R.string.compte_invite_texte)
                bouton.visibility = View.VISIBLE
                bouton.setText(R.string.compte_connexion)
                bouton.setOnClickListener { Connexion.demarrer(a) }
                lien.visibility = View.GONE
            }
        }
        // Écran de bienvenue : même état, en plus court.
        bienvenue.visibility = if (u == null) View.VISIBLE else View.GONE
        bienvenue.setText(if (e.enCours) R.string.compte_rouvrir else R.string.compte_connexion)
        bienvenueTexte.text = when {
            u != null -> a.getString(R.string.compte_connecte, u.nom)
            e.enCours && e.code != null -> a.getString(R.string.compte_attente_code, e.code)
            e.erreur != null -> e.erreur
            else -> a.getString(R.string.compte_invite_texte)
        }
    }
}

/**
 * Onglet Bibliothèque : le catalogue en ligne, téléchargeable sans compte. Avec un compte : aimer un morceau
 * et partager les siens (ils passent par la modération du serveur avant d'apparaître).
 */
class PageBiblio(private val a: AppCompatActivity, private val biblio: Bibliotheque, private val surAjout: () -> Unit) {
    private val recherche = a.findViewById<EditText>(R.id.biblioRecherche)
    private val etat = a.findViewById<TextView>(R.id.biblioEtat)
    private val liste = a.findViewById<ViewGroup>(R.id.biblioListe)
    private val plus = a.findViewById<View>(R.id.biblioPlus)
    private val filtreTag = a.findViewById<TextView>(R.id.filtreTag)
    private val filtreInstrument = a.findViewById<TextView>(R.id.filtreInstrument)
    private val tris = mapOf(R.id.triRecents to "recent", R.id.triPopulaires to "popular", R.id.triAimes to "likes")

    private var tri = "recent"
    private var tag = ""
    private var instrument = ""
    private var page = 0
    private var pages = 1
    private var demande = 0
    private var charge = false

    init {
        for ((id, cle) in tris) {
            a.findViewById<View>(id).setOnClickListener {
                tri = cle
                charger(premiere = true)
            }
        }
        a.findViewById<View>(R.id.biblioChercher).setOnClickListener { chercher() }
        recherche.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_SEARCH) chercher()
            action == EditorInfo.IME_ACTION_SEARCH
        }
        plus.setOnClickListener { charger(premiere = false) }
        filtreTag.setOnClickListener {
            choisirFiltre(R.string.filtre_tag_titre, Serveur.TAGS, R.array.tags_noms, tag) { tag = it }
        }
        filtreInstrument.setOnClickListener {
            choisirFiltre(R.string.filtre_instrument_titre, Serveur.INSTRUMENTS, R.array.instruments_noms, instrument) { instrument = it }
        }
        a.findViewById<View>(R.id.biblioPartager).setOnClickListener { partager() }
        majFiltres()
        CarteMiseAJour(a)
        // Le cœur d'un morceau dépend du compte : la liste est relue quand on se connecte ou se déconnecte.
        var compte = Compte.utilisateur.value?.id
        Compte.utilisateur.observe(a) { u ->
            if (u?.id != compte) {
                compte = u?.id
                if (charge) charger(premiere = true)
            }
        }
    }

    /** À l'ouverture de l'onglet : la première page, une seule fois. */
    fun ouvrir() {
        if (!charge) charger(premiere = true)
    }

    private fun chercher() {
        a.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(recherche.windowToken, 0)
        recherche.clearFocus()
        charger(premiere = true)
    }

    // ------------------------------------------------------------------ filtres

    private fun nom(cles: List<String>, noms: Int, cle: String): String =
        a.resources.getStringArray(noms).getOrNull(cles.indexOf(cle)) ?: a.getString(R.string.filtre_tous)

    private fun majFiltres() {
        filtreTag.text = a.getString(R.string.filtre_tag, nom(Serveur.TAGS, R.array.tags_noms, tag))
        filtreTag.isSelected = tag.isNotEmpty()
        filtreInstrument.text = a.getString(R.string.filtre_instrument, nom(Serveur.INSTRUMENTS, R.array.instruments_noms, instrument))
        filtreInstrument.isSelected = instrument.isNotEmpty()
    }

    /** Une liste à choix unique : « aucun filtre » puis chaque valeur que connaît le serveur. */
    private fun choisirFiltre(titre: Int, cles: List<String>, noms: Int, actuel: String, retenir: (String) -> Unit) {
        val libelles = arrayOf(a.getString(R.string.filtre_aucun)) + a.resources.getStringArray(noms)
        AlertDialog.Builder(a)
            .setTitle(titre)
            .setSingleChoiceItems(libelles, cles.indexOf(actuel) + 1) { dialogue, i ->
                dialogue.dismiss()
                retenir(if (i == 0) "" else cles.getOrElse(i - 1) { "" })
                majFiltres()
                charger(premiere = true)
            }
            .setNegativeButton(R.string.annuler, null)
            .show()
    }

    // ------------------------------------------------------------------ liste

    private fun charger(premiere: Boolean) {
        for ((id, cle) in tris) a.findViewById<View>(id).isSelected = cle == tri
        val numero = if (premiere) 1 else page + 1
        val moi = ++demande
        if (premiere) liste.removeAllViews()
        plus.visibility = View.GONE
        etat.visibility = View.VISIBLE
        etat.setText(R.string.biblio_chargement)
        val q = URLEncoder.encode(recherche.text.toString().trim().take(80), "UTF-8")
        val chemin = "/api/songs?q=$q&page=$numero&per_page=30&sort=$tri" +
            "&tag=" + URLEncoder.encode(tag, "UTF-8") + "&instrument=" + URLEncoder.encode(instrument, "UTF-8")
        Serveur.fil.execute {
            val resultat: Any = try {
                Serveur.lire(a, chemin, Compte.jeton(a))
            } catch (e: ErreurEnLigne) {
                e
            }
            a.runOnUiThread {
                if (moi != demande || a.isDestroyed) return@runOnUiThread
                if (resultat is JSONObject) afficher(resultat, numero) else etat.text = (resultat as ErreurEnLigne).message
            }
        }
    }

    private fun afficher(r: JSONObject, numero: Int) {
        charge = true
        page = numero
        pages = r.optInt("pages", 1)
        val morceaux = r.optJSONArray("items")
        val combien = morceaux?.length() ?: 0
        for (i in 0 until combien) ligne(morceaux!!.optJSONObject(i) ?: continue)
        if (liste.childCount == 0) {
            etat.setText(R.string.biblio_vide)
        } else {
            etat.visibility = View.GONE
        }
        plus.visibility = if (page < pages) View.VISIBLE else View.GONE
    }

    private fun ligne(o: JSONObject) {
        val numero = o.optInt("id")
        val sha = o.optString("sha256")
        val titre = o.optString("title")
        val vue = a.layoutInflater.inflate(R.layout.item_morceau_en_ligne, liste, false)
        vue.findViewById<TextView>(R.id.titre).text = titre
        val artiste = if (o.isNull("artist")) "" else o.optString("artist")
        val meta = vue.findViewById<TextView>(R.id.meta)
        val coeur = vue.findViewById<ImageView>(R.id.aime)
        var aime = o.optBoolean("liked_by_me")
        var nombre = o.optInt("likes")
        fun majAime() {
            meta.text = listOfNotNull(
                artiste.ifBlank { null },
                minutes((o.optDouble("duration_s", 0.0) * 1000).toLong()),
                a.getString(R.string.biblio_aime, nombre),
                a.getString(R.string.biblio_telecharge, o.optInt("downloads")),
            ).joinToString(" · ")
            coeur.setColorFilter(a.getColor(if (aime) R.color.c_rose else R.color.c_text_2))
            coeur.isSelected = aime
        }
        majAime()
        coeur.setOnClickListener {
            val jeton = Compte.jeton(a)
            if (jeton == null || Compte.utilisateur.value == null) {
                Toast.makeText(a, R.string.biblio_aimer_compte, Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }
            val voulu = !aime
            coeur.isEnabled = false
            coeur.alpha = 0.4f
            Serveur.fil.execute {
                val resultat: Any = try {
                    Serveur.aimer(a, numero, jeton, voulu)
                } catch (e: ErreurEnLigne) {
                    e
                }
                a.runOnUiThread {
                    if (a.isDestroyed) return@runOnUiThread
                    coeur.isEnabled = true
                    coeur.alpha = 1f
                    if (resultat is Int) {
                        aime = voulu
                        nombre = resultat
                        majAime()
                    } else {
                        Toast.makeText(a, (resultat as ErreurEnLigne).message, Toast.LENGTH_LONG).show()
                    }
                }
            }
        }
        val action = vue.findViewById<ImageView>(R.id.action)
        fun dejaLa() {
            action.setImageResource(R.drawable.ic_coche)
            action.setColorFilter(a.getColor(R.color.c_ok))
            action.isClickable = false
            action.contentDescription = a.getString(R.string.biblio_deja)
        }
        if (biblio.parSha(sha) != null) {
            dejaLa()
        } else {
            action.setOnClickListener {
                action.isEnabled = false
                action.alpha = 0.4f
                Serveur.fil.execute {
                    val erreur = try {
                        biblio.ajouter(Serveur.telecharger(a, "/api/songs/$numero/download", Compte.jeton(a), sha), titre, numero)
                        null
                    } catch (e: ErreurEnLigne) {
                        e.message
                    } catch (e: IOException) {
                        a.getString(R.string.erreur_fichier)
                    } catch (e: MidiIllisible) {
                        a.getString(R.string.erreur_fichier)
                    }
                    a.runOnUiThread {
                        if (a.isDestroyed) return@runOnUiThread
                        action.isEnabled = true
                        action.alpha = 1f
                        if (erreur == null) {
                            dejaLa()
                            surAjout()
                            Toast.makeText(a, a.getString(R.string.import_ok, titre), Toast.LENGTH_SHORT).show()
                        } else {
                            Toast.makeText(a, erreur, Toast.LENGTH_LONG).show()
                        }
                    }
                }
            }
        }
        liste.addView(vue)
    }

    // ------------------------------------------------------------------ partager un de ses morceaux

    private fun partager() {
        if (Compte.utilisateur.value == null) {
            Toast.makeText(a, R.string.partage_compte, Toast.LENGTH_LONG).show()
            Connexion.demarrer(a)
            return
        }
        val morceaux = biblio.partageables()
        if (morceaux.isEmpty()) {
            Toast.makeText(a, R.string.partage_aucun, Toast.LENGTH_LONG).show()
            return
        }
        AlertDialog.Builder(a)
            .setTitle(R.string.partage_choisir)
            .setItems(morceaux.map { it.titre }.toTypedArray()) { _, i -> formulairePartage(morceaux[i]) }
            .setNegativeButton(R.string.annuler, null)
            .show()
    }

    /** Titre, provenance du fichier et tags : ce que le serveur demande avec le fichier (clean_song_meta côté PC). */
    private fun formulairePartage(m: Morceau) {
        val marge = (20 * a.resources.displayMetrics.density).toInt()
        val boite = LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(marge, marge / 2, marge, 0)
        }
        fun libelle(texte: String) = TextView(a).apply {
            text = texte
            setTextColor(a.getColor(R.color.c_ink))
            setPadding(0, marge / 2, 0, marge / 4)
        }
        val titre = EditText(a).apply {
            setText(m.titre)
            hint = a.getString(R.string.partage_champ_titre)
            isSingleLine = true
            filters = arrayOf(InputFilter.LengthFilter(120))
        }
        boite.addView(libelle(a.getString(R.string.partage_champ_titre)))
        boite.addView(titre)

        boite.addView(libelle(a.getString(R.string.partage_licence)))
        val licences = RadioGroup(a)
        for ((i, nom) in a.resources.getStringArray(R.array.licences_noms).withIndex()) {
            licences.addView(RadioButton(a).apply { id = i + 1; text = nom })
        }
        licences.check(Serveur.LICENCES.indexOf("unknown") + 1)
        boite.addView(licences)

        boite.addView(libelle(a.getString(R.string.partage_tags, Serveur.TAGS_MAX)))
        val cases = ArrayList<CheckBox>()
        for (nom in a.resources.getStringArray(R.array.tags_noms)) {
            val case = CheckBox(a).apply { text = nom }
            case.setOnCheckedChangeListener { bouton, coche ->
                // Le serveur refuse plus de huit tags : la neuvième case ne se coche pas.
                if (coche && cases.count { it.isChecked } > Serveur.TAGS_MAX) bouton.isChecked = false
            }
            cases.add(case)
            boite.addView(case)
        }

        val dialogue = AlertDialog.Builder(a)
            .setTitle(R.string.partage_titre)
            .setView(ScrollView(a).apply { addView(boite) })
            .setNegativeButton(R.string.annuler, null)
            .setPositiveButton(R.string.partage_envoyer, null)
            .create()
        dialogue.show()
        // Le bouton est branché après coup : un titre vide ne doit pas fermer le formulaire.
        dialogue.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val saisi = titre.text.toString().trim()
            if (saisi.isEmpty()) {
                Toast.makeText(a, R.string.partage_titre_requis, Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val licence = Serveur.LICENCES.getOrElse(licences.checkedRadioButtonId - 1) { "unknown" }
            val tags = Serveur.TAGS.filterIndexed { i, _ -> cases[i].isChecked }
            dialogue.dismiss()
            envoyerPartage(m, saisi, licence, tags)
        }
    }

    private fun envoyerPartage(m: Morceau, titre: String, licence: String, tags: List<String>) {
        val jeton = Compte.jeton(a) ?: return
        Toast.makeText(a, a.getString(R.string.partage_envoi, titre), Toast.LENGTH_SHORT).show()
        Serveur.fil.execute {
            val message = try {
                Serveur.partager(a, jeton, titre, biblio.octets(m.id), tags, "", licence)
                biblio.noterPartage(m.id)
                a.getString(R.string.partage_ok, titre)
            } catch (e: ErreurEnLigne) {
                if (e.cle == "duplicate") {
                    biblio.noterPartage(m.id)
                    a.getString(R.string.partage_deja)
                } else {
                    e.message.orEmpty()
                }
            } catch (e: IOException) {
                a.getString(R.string.erreur_fichier)
            }
            a.runOnUiThread {
                if (!a.isDestroyed) Toast.makeText(a, message, Toast.LENGTH_LONG).show()
            }
        }
    }
}

/**
 * La carte « mise à jour » en haut de la bibliothèque : cachée tant que l'appli est à jour, puis
 * télécharger, suivre l'avancement, installer. La vérification part une fois, à la création.
 */
class CarteMiseAJour(private val a: AppCompatActivity) {
    private val carte = a.findViewById<View>(R.id.majCarte)
    private val titre = a.findViewById<TextView>(R.id.majTitre)
    private val texte = a.findViewById<TextView>(R.id.majTexte)
    private val bouton = a.findViewById<TextView>(R.id.majBouton)

    init {
        MiseAJour.etat.observe(a) { afficher(it) }
        MiseAJour.verifier(a)
    }

    private fun afficher(e: MiseAJour.Etat) {
        val v = e.version
        carte.visibility = if (v == null) View.GONE else View.VISIBLE
        if (v == null) return
        titre.text = a.getString(R.string.maj_titre, v.version)
        val taille = a.getString(R.string.maj_taille, String.format(Locale.ROOT, "%.1f", v.taille / 1048576.0))
        bouton.isEnabled = e.progression == null
        bouton.alpha = if (e.progression == null) 1f else 0.6f
        when {
            e.progression != null -> {
                texte.text = taille
                bouton.text = a.getString(R.string.maj_progression, e.progression)
            }
            e.fichier != null -> {
                texte.setText(R.string.maj_prete)
                bouton.setText(R.string.maj_installer)
                bouton.setOnClickListener { MiseAJour.installer(a, v, e.fichier) }
            }
            else -> {
                texte.text = e.erreur ?: listOf(taille, v.notes.trim()).filter { it.isNotEmpty() }.joinToString("\n")
                bouton.setText(R.string.maj_telecharger)
                bouton.setOnClickListener {
                    // Sans le droit d'installer depuis l'appli, autant laisser le navigateur télécharger l'APK.
                    if (MiseAJour.peutInstaller(a)) MiseAJour.telecharger(a, v) else Connexion.ouvrir(a, v.adresse)
                }
            }
        }
    }
}

/**
 * Le choix des pistes d'un morceau de « Mes morceaux » : celles qu'on décoche ne sont plus jouées
 * (skip_tracks côté PC). Le choix est gardé par morceau ; il ne touche pas aux salons.
 */
object DialoguePistes {
    /** [surChangement] est appelé sur le fil principal quand le choix a changé (la couverture affichée aussi). */
    fun ouvrir(a: AppCompatActivity, biblio: Bibliotheque, m: Morceau, surChangement: () -> Unit) {
        Serveur.fil.execute {
            val pistes = try {
                biblio.pistes(m.id)
            } catch (e: IOException) {
                emptyList()
            } catch (e: MidiIllisible) {
                emptyList()
            }
            a.runOnUiThread {
                if (a.isDestroyed) return@runOnUiThread
                if (pistes.size < 2) {
                    Toast.makeText(a, R.string.pistes_une_seule, Toast.LENGTH_SHORT).show()
                    return@runOnUiThread
                }
                val coupees = biblio.pistesCoupees(m.id)
                val gardees = BooleanArray(pistes.size) { pistes[it].index !in coupees }
                val libelles = pistes.map { p ->
                    a.getString(R.string.pistes_detail, p.nom.ifBlank { a.getString(R.string.salon_piste_n, p.index + 1) }, p.notes)
                }.toTypedArray()
                AlertDialog.Builder(a)
                    .setTitle(R.string.pistes_titre)
                    .setMultiChoiceItems(libelles, gardees) { _, i, coche -> gardees[i] = coche }
                    .setNegativeButton(R.string.annuler, null)
                    .setPositiveButton(R.string.valider) { _, _ ->
                        if (gardees.none { it }) {
                            Toast.makeText(a, R.string.pistes_garder_une, Toast.LENGTH_SHORT).show()
                        } else {
                            biblio.definirPistesCoupees(m.id, pistes.filterIndexed { i, _ -> !gardees[i] }.map { it.index }.toSet())
                            surChangement()
                        }
                    }
                    .show()
            }
        }
    }
}

/** Onglet Salon : créer ou rejoindre, puis l'état du salon. Les mêmes commandes existent dans la bulle, pendant le jeu. */
class PageSalon(private val a: AppCompatActivity, private val biblio: Bibliotheque) {
    private val message = a.findViewById<TextView>(R.id.salonMessage)
    private val hors = a.findViewById<View>(R.id.salonHors)
    private val dans = a.findViewById<View>(R.id.salonDans)
    private val code = a.findViewById<EditText>(R.id.salonCode)
    private val retard = a.findViewById<TextView>(R.id.salonRetardValeur)

    init {
        a.findViewById<View>(R.id.salonCreer).setOnClickListener { siConnecte { Salon.creer(a) } }
        a.findViewById<View>(R.id.salonRejoindre).setOnClickListener { rejoindre() }
        code.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_GO) rejoindre()
            action == EditorInfo.IME_ACTION_GO
        }
        a.findViewById<View>(R.id.salonPartager).setOnClickListener {
            val envoi = Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, a.getString(R.string.salon_invitation, Salon.code.orEmpty()))
            a.startActivity(Intent.createChooser(envoi, a.getString(R.string.salon_partager)))
        }
        a.findViewById<View>(R.id.salonChoisir).setOnClickListener { choisirMorceau() }
        a.findViewById<View>(R.id.salonRejoindreLecture).setOnClickListener {
            if (Salon.attenteRejoindre) Salon.annulerRejoindre() else Salon.rejoindreLecture()
        }
        a.findViewById<View>(R.id.salonRepartir).setOnClickListener { Salon.repartirPistes() }
        a.findViewById<View>(R.id.salonToutJouer).setOnClickListener { Salon.arreterOrchestre() }
        a.findViewById<View>(R.id.salonRetardMoins).setOnClickListener { decaler(-PAS_RETARD_MS) }
        a.findViewById<View>(R.id.salonRetardPlus).setOnClickListener { decaler(PAS_RETARD_MS) }
        decaler(0)
        a.findViewById<View>(R.id.salonPretAppli).setOnClickListener { Salon.basculerPret() }
        a.findViewById<View>(R.id.salonLancerAppli).setOnClickListener {
            if (Salon.etat == "lobby") Salon.lancer() else Salon.arreter()
        }
        a.findViewById<View>(R.id.salonQuitter).setOnClickListener { Salon.quitter() }
        Salon.changement.observe(a) { afficher() }
        Compte.utilisateur.observe(a) { afficher() }
    }

    /** Les salons demandent un compte : sans lui, on lance la connexion plutôt que d'afficher un refus. */
    private fun siConnecte(action: () -> Unit) {
        if (Compte.utilisateur.value == null) {
            Toast.makeText(a, R.string.salon_compte_requis, Toast.LENGTH_LONG).show()
            Connexion.demarrer(a)
        } else {
            action()
        }
    }

    private fun rejoindre() {
        a.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(code.windowToken, 0)
        siConnecte { Salon.rejoindre(a, code.text.toString()) }
    }

    private fun choisirMorceau() {
        val morceaux = biblio.liste()
        AlertDialog.Builder(a)
            .setTitle(R.string.salon_choisir)
            .setItems(morceaux.map { it.titre }.toTypedArray()) { _, i -> Salon.choisirMorceau(morceaux[i]) }
            .show()
    }

    /** Avance / retard : le réglage vaut pour le prochain départ, il ne déplace pas un morceau déjà parti. */
    private fun decaler(pas: Int) {
        val valeur = Salon.definirAvanceRetard(a, Salon.avanceRetard(a) + pas)
        retard.text = String.format(Locale.ROOT, "%+d ms", valeur)
    }

    /** Chef : les pistes que joue ce joueur. Tout cocher (ou rien) lui rend tout le morceau. */
    private fun choisirPartie(j: Salon.Joueur, pistes: List<PisteMidi>) {
        val actuelle = Salon.partie(j.id)
        val cochees = BooleanArray(pistes.size) { actuelle == null || pistes[it].index in actuelle.pistes }
        val libelles = pistes.map { p ->
            a.getString(R.string.pistes_detail, p.nom.ifBlank { a.getString(R.string.salon_piste_n, p.index + 1) }, p.notes)
        }.toTypedArray()
        AlertDialog.Builder(a)
            .setTitle(a.getString(R.string.orchestre_partie_de, j.nom))
            .setMultiChoiceItems(libelles, cochees) { _, i, coche -> cochees[i] = coche }
            .setNegativeButton(R.string.annuler, null)
            .setPositiveButton(R.string.valider) { _, _ ->
                val choix = pistes.filterIndexed { i, _ -> cochees[i] }.map { it.index }
                Salon.definirPartie(j.id, if (choix.size == pistes.size) emptyList() else choix, actuelle?.octave)
            }
            .show()
    }

    private fun exclure(j: Salon.Joueur) {
        AlertDialog.Builder(a)
            .setMessage(a.getString(R.string.salon_exclure_question, j.nom))
            .setNegativeButton(R.string.annuler, null)
            .setPositiveButton(R.string.salon_exclure) { _, _ -> Salon.exclure(j.id) }
            .show()
    }

    private fun afficher() {
        val texte = when {
            Salon.message.isNotEmpty() -> Salon.message
            Salon.enConnexion -> a.getString(R.string.salon_connexion)
            else -> ""
        }
        message.text = texte
        message.visibility = if (texte.isEmpty()) View.GONE else View.VISIBLE
        hors.visibility = if (Salon.actif) View.GONE else View.VISIBLE
        dans.visibility = if (Salon.actif) View.VISIBLE else View.GONE
        if (!Salon.actif) return

        val repos = Salon.etat == "lobby"
        a.findViewById<TextView>(R.id.salonCodeGrand).text = Salon.code
        val m = Salon.morceau
        a.findViewById<TextView>(R.id.salonMorceauNom).text = when {
            m == null -> a.getString(if (Salon.hote) R.string.salon_sans_morceau_chef else R.string.salon_sans_morceau)
            Salon.telechargement -> a.getString(R.string.salon_telechargement, m.nom)
            else -> "${m.nom} · ${minutes(m.dureeMs)}"
        }
        a.findViewById<View>(R.id.salonChoisir).apply {
            visibility = if (Salon.hote) View.VISIBLE else View.GONE
            isEnabled = repos
        }
        a.findViewById<TextView>(R.id.salonRejoindreLecture).apply {
            visibility = if (Salon.attenteRejoindre || Salon.positionARejoindre() != null) View.VISIBLE else View.GONE
            setText(if (Salon.attenteRejoindre) R.string.salon_rejoindre_annuler else R.string.salon_rejoindre_lecture)
        }

        // Orchestre : il faut au moins deux pistes à se partager ; un invité ne voit la carte que si le chef a réparti.
        val pistes = m?.pistes.orEmpty().filter { !it.percussions }
        val orchestre = Salon.orchestre
        val partageable = pistes.size >= 2
        a.findViewById<View>(R.id.salonOrchestre).visibility =
            if (partageable && (Salon.hote || orchestre)) View.VISIBLE else View.GONE
        a.findViewById<TextView>(R.id.salonOrchestreEtat).text = when {
            !orchestre -> a.getString(R.string.orchestre_inactif)
            Salon.hote -> a.getString(R.string.orchestre_actif_chef)
            else -> a.getString(R.string.orchestre_actif, Salon.libellePartie(Salon.monId).ifEmpty { a.getString(R.string.orchestre_tout) })
        }
        a.findViewById<View>(R.id.salonOrchestreBoutons).visibility = if (Salon.hote) View.VISIBLE else View.GONE
        a.findViewById<View>(R.id.salonRepartir).isEnabled = repos
        a.findViewById<View>(R.id.salonToutJouer).apply {
            visibility = if (orchestre) View.VISIBLE else View.GONE
            isEnabled = repos
        }

        a.findViewById<TextView>(R.id.salonJoueursTitre).text =
            a.resources.getQuantityString(R.plurals.salon_joueurs, Salon.joueurs.size, Salon.joueurs.size)
        val liste = a.findViewById<ViewGroup>(R.id.salonJoueurs)
        liste.removeAllViews()
        for (j in Salon.joueurs) {
            val vue = a.layoutInflater.inflate(R.layout.item_joueur, liste, false)
            vue.findViewById<TextView>(R.id.initiale).text = j.nom.take(1).uppercase()
            vue.findViewById<TextView>(R.id.nom).text = if (j.id == Salon.monId) a.getString(R.string.salon_moi, j.nom) else j.nom
            val role = a.getString(
                when {
                    !j.connecte -> R.string.joueur_deconnecte
                    j.hote -> R.string.joueur_chef
                    else -> R.string.joueur_invite
                }
            )
            val partie = if (orchestre) Salon.libellePartie(j.id).ifEmpty { a.getString(R.string.orchestre_tout) } else ""
            vue.findViewById<TextView>(R.id.detail).text =
                if (partie.isEmpty()) role else a.getString(R.string.joueur_detail_partie, role, partie)
            val ok = j.statut == "playing" || j.statut == "armed" || (j.pret && j.aLeMorceau)
            vue.findViewById<TextView>(R.id.etat).apply {
                setText(
                    when {
                        j.statut == "playing" -> R.string.joueur_joue
                        j.statut == "armed" -> R.string.joueur_arme
                        m != null && !j.aLeMorceau -> R.string.joueur_sans_morceau
                        j.pret -> R.string.joueur_pret
                        else -> R.string.joueur_attente
                    }
                )
                setBackgroundResource(if (ok) R.drawable.pilule_ok else R.drawable.pilule_attente)
                setTextColor(a.getColor(if (ok) R.color.c_ok else R.color.c_ambre_texte))
            }
            if (Salon.hote && repos && partageable) vue.setOnClickListener { choisirPartie(j, pistes) }
            vue.findViewById<View>(R.id.exclure).apply {
                visibility = if (Salon.hote && j.id != Salon.monId) View.VISIBLE else View.GONE
                setOnClickListener { exclure(j) }
            }
            liste.addView(vue)
        }

        a.findViewById<TextView>(R.id.salonPretAppli).apply {
            setText(if (Salon.pret) R.string.salon_plus_pret else R.string.salon_pret)
            setBackgroundResource(if (Salon.pret) R.drawable.btn_creme else R.drawable.btn_ambre)
            isEnabled = repos
        }
        a.findViewById<TextView>(R.id.salonLancerAppli).apply {
            visibility = if (Salon.hote) View.VISIBLE else View.GONE
            setText(if (repos) R.string.salon_lancer else R.string.salon_arreter)
            isEnabled = !repos || m != null
        }
    }

    private companion object {
        const val PAS_RETARD_MS = 10
    }
}

/** Onglet Dessin : choisir une image et un format de toile, voir le résultat en 16 couleurs. La bulle la peint dans le jeu. */
class PageDessin(private val a: AppCompatActivity) {
    private val apercu = a.findViewById<ImageView>(R.id.dessinApercu)
    private val infos = a.findViewById<TextView>(R.id.dessinInfos)
    private val formats = a.findViewById<ViewGroup>(R.id.dessinFormats)
    private var format = Dessin.FORMATS[0]
    private var source: android.net.Uri? = null

    private val choix = a.registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            source = uri
            convertir()
        }
    }

    init {
        a.findViewById<View>(R.id.dessinChoisir).setOnClickListener { choix.launch("image/*") }
        Dessin.charger(a)?.let { t ->
            format = Dessin.FORMATS.first { it.nom == t.format }
            montrer(t)
        }
        for (f in Dessin.FORMATS) {
            val puce = a.layoutInflater.inflate(R.layout.item_format, formats, false) as TextView
            puce.text = f.nom
            puce.setOnClickListener {
                format = f
                majFormats()
                // Changer de format recadre l'image : il faut la relire, pas réutiliser la grille déjà réduite.
                if (source != null) convertir()
            }
            formats.addView(puce)
        }
        majFormats()
    }

    private fun majFormats() {
        for (i in 0 until formats.childCount) formats.getChildAt(i).isSelected = Dessin.FORMATS[i] === format
    }

    private fun convertir() {
        val uri = source ?: return
        val f = format
        infos.setText(R.string.biblio_chargement)
        Serveur.fil.execute {
            val travail = try {
                a.contentResolver.openInputStream(uri)?.use { android.graphics.BitmapFactory.decodeStream(it) }?.let { image ->
                    Dessin.convertir(image, f).also { image.recycle() }
                }
            } catch (e: IOException) {
                null
            } catch (e: SecurityException) {
                null
            } catch (e: OutOfMemoryError) {
                null
            }
            a.runOnUiThread {
                if (a.isDestroyed) return@runOnUiThread
                if (travail == null) {
                    infos.setText(R.string.dessin_illisible)
                } else {
                    Dessin.enregistrer(a, travail)
                    montrer(travail)
                }
            }
        }
    }

    private fun montrer(t: Dessin.Travail) {
        apercu.visibility = View.VISIBLE
        apercu.setImageBitmap(Dessin.apercu(t, 600))
        val traits = Dessin.traits(t).size
        infos.text = a.getString(R.string.dessin_infos, t.format, t.largeur, t.hauteur, t.couleurs, traits)
    }
}
