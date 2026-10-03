package fr.cyberdodo.dodotopia

import android.content.Context
import android.util.Log
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Journal des mesures de l'étape 1 : un fichier horodaté dans filesDir (partagé depuis l'activité)
 * doublé dans Logcat. Les écritures sont synchrones : ne jamais l'appeler dans la boucle temps réel
 * du métronome, qui garde ses mesures en mémoire et les écrit à la fin.
 */
object SpikeLog {
    const val TAG = "DodoSpike"
    private const val NOM = "spike.log"

    private val horodatage = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.FRANCE)

    @Volatile
    private var fichier: File? = null

    fun init(context: Context) {
        if (fichier == null) fichier = File(context.applicationContext.filesDir, NOM)
    }

    fun fichier(context: Context): File {
        init(context)
        return fichier!!
    }

    @Synchronized
    fun log(message: String) {
        Log.i(TAG, message)
        val f = fichier ?: return
        try {
            val date = horodatage.format(Date())
            // Un message de plusieurs lignes garde son horodatage sur chaque ligne : le journal reste triable.
            f.appendText(message.lineSequence().joinToString("") { "$date  $it\n" })
        } catch (e: IOException) {
            Log.w(TAG, "Journal non écrit : ${e.message}")
        }
    }

    @Synchronized
    fun effacer() {
        fichier?.delete()
    }
}
