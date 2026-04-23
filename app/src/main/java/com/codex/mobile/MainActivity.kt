package com.codex.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    CodexMobileApp(modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}

@Composable
private fun CodexMobileApp(modifier: Modifier = Modifier) {
    var apiKey by remember { mutableStateOf("") }
    var prompt by remember { mutableStateOf("Help me plan my coding task") }
    var output by remember { mutableStateOf("Response appears here") }
    var isLoading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "Codex Mobile",
            style = MaterialTheme.typography.headlineMedium
        )
        Text(
            text = "Enter your OpenAI API key and send prompts to Codex from your Android device.",
            style = MaterialTheme.typography.bodyMedium
        )

        OutlinedTextField(
            modifier = Modifier.fillMaxWidth(),
            value = apiKey,
            onValueChange = { apiKey = it.trim() },
            label = { Text("OpenAI API key") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true
        )

        OutlinedTextField(
            modifier = Modifier.fillMaxWidth(),
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("Prompt") },
            minLines = 4,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences)
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Button(
                onClick = {
                    scope.launch {
                        isLoading = true
                        error = null
                        runCatching {
                            withContext(Dispatchers.IO) {
                                CodexApiClient().generateResponse(apiKey = apiKey, prompt = prompt)
                            }
                        }.onSuccess {
                            output = it
                        }.onFailure {
                            error = it.message ?: "Unknown error"
                        }
                        isLoading = false
                    }
                },
                enabled = !isLoading && apiKey.isNotBlank() && prompt.isNotBlank()
            ) {
                Text("Ask Codex")
            }

            if (isLoading) {
                CircularProgressIndicator()
            }
        }

        if (error != null) {
            Text(
                text = "Error: $error",
                color = MaterialTheme.colorScheme.error
            )
        }

        Text(text = "Result", style = MaterialTheme.typography.titleMedium)
        Text(text = output, style = MaterialTheme.typography.bodyLarge)
    }
}

private class CodexApiClient {
    private val client = OkHttpClient()
    private val json = Json { ignoreUnknownKeys = true }

    fun generateResponse(apiKey: String, prompt: String): String {
        require(apiKey.isNotBlank()) { "API key is required" }
        require(prompt.isNotBlank()) { "Prompt is required" }

        val payload = ResponseRequest(
            model = "gpt-5-codex",
            input = prompt
        )

        val request = Request.Builder()
            .url("https://api.openai.com/v1/responses")
            .addHeader("Authorization", "Bearer $apiKey")
            .addHeader("Content-Type", "application/json")
            .post(json.encodeToString(ResponseRequest.serializer(), payload).toRequestBody(JSON_MEDIA_TYPE))
            .build()

        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException("OpenAI request failed (${response.code}): $body")
            }

            val parsed = json.decodeFromString(ResponseApiResponse.serializer(), body)
            return parsed.outputText
                ?: parsed.output
                    .flatMap { it.content }
                    .firstOrNull { it.type == "output_text" }
                    ?.text
                ?: "No text response returned"
        }
    }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}

@Serializable
private data class ResponseRequest(
    val model: String,
    val input: String
)

@Serializable
private data class ResponseApiResponse(
    @SerialName("output_text") val outputText: String? = null,
    val output: List<ResponseOutputItem> = emptyList()
)

@Serializable
private data class ResponseOutputItem(
    val content: List<ResponseContent> = emptyList()
)

@Serializable
private data class ResponseContent(
    val type: String,
    val text: String? = null
)
