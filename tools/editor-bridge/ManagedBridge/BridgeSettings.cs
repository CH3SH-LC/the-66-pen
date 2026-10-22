using System;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Miliastra.EditorBridge
{
    /// <summary>
    /// Strict, fixed-schema bridge settings. Unknown members are rejected, so a typo in the
    /// generated config fails closed instead of being silently ignored.
    ///
    /// Required shape (JSON object, exactly these six members):
    /// {
    ///   "pid":            <int&gt;0&gt;        target process id
    ///   "startUtcTicks":  <int&gt;0&gt;        Process.StartTime.ToUniversalTime().Ticks of that pid
    ///   "nonce":          "<64 hex chars>"  32 random bytes, hex encoded
    ///   "pipeName":       "<name>"          named pipe name, no path prefix
    ///   "expiresUtc":     "<iso-8601>"      absolute lease deadline, must carry Z or +hh:mm offset
    ///   "expectedExe":    "<abs path>"      absolute path of the target executable
    /// }
    ///
    /// "pid" and "startUtcTicks" may also be JSON strings (they exceed 2^53 and would lose
    /// precision in a JavaScript producer).
    /// </summary>
    [JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
    internal sealed class BridgeSettings
    {
        internal const int NonceBytes = 32;
        internal const int NonceHexLength = NonceBytes * 2;

        [JsonPropertyName("pid")]
        [JsonConverter(typeof(LongFromNumberOrStringConverter))]
        public long Pid { get; set; }

        [JsonPropertyName("startUtcTicks")]
        [JsonConverter(typeof(LongFromNumberOrStringConverter))]
        public long StartUtcTicks { get; set; }

        [JsonPropertyName("nonce")]
        public string Nonce { get; set; } = string.Empty;

        [JsonPropertyName("pipeName")]
        public string PipeName { get; set; } = string.Empty;

        [JsonPropertyName("expiresUtc")]
        public string ExpiresUtc { get; set; } = string.Empty;

        [JsonPropertyName("expectedExe")]
        public string ExpectedExe { get; set; } = string.Empty;

        internal DateTimeOffset ExpiresAtUtc { get; private set; }

        /// <summary>Returns null when valid, otherwise a short machine-readable reason code.</summary>
        internal string? Validate()
        {
            if (Pid <= 0)
            {
                return "pid_not_positive";
            }
            if (StartUtcTicks <= 0)
            {
                return "start_utc_ticks_not_positive";
            }
            if (Nonce.Length != NonceHexLength || !IsHex(Nonce))
            {
                return "nonce_not_32_bytes_hex";
            }
            if (PipeName.Length == 0 || PipeName.Length > 200 || !IsPipeNameCharset(PipeName))
            {
                return "pipe_name_invalid";
            }
            if (ExpectedExe.Length == 0 || !Path.IsPathFullyQualified(ExpectedExe))
            {
                return "expected_exe_not_absolute";
            }

            var stamp = ExpiresUtc.Trim();
            if (!HasExplicitUtcOffset(stamp))
            {
                return "expires_utc_missing_offset";
            }
            if (!DateTimeOffset.TryParse(
                    stamp,
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.RoundtripKind | DateTimeStyles.AdjustToUniversal,
                    out var parsed))
            {
                return "expires_utc_unparsable";
            }
            ExpiresAtUtc = parsed;
            return null;
        }

        private static bool IsHex(string value)
        {
            for (var i = 0; i < value.Length; i++)
            {
                if (HexValue(value[i]) < 0)
                {
                    return false;
                }
            }
            return true;
        }

        internal static int HexValue(char c)
        {
            if (c >= '0' && c <= '9')
            {
                return c - '0';
            }
            if (c >= 'a' && c <= 'f')
            {
                return c - 'a' + 10;
            }
            if (c >= 'A' && c <= 'F')
            {
                return c - 'A' + 10;
            }
            return -1;
        }

        private static bool IsPipeNameCharset(string value)
        {
            for (var i = 0; i < value.Length; i++)
            {
                var c = value[i];
                var ok = (c >= 'a' && c <= 'z')
                         || (c >= 'A' && c <= 'Z')
                         || (c >= '0' && c <= '9')
                         || c == '.' || c == '_' || c == '-';
                if (!ok)
                {
                    return false;
                }
            }
            return true;
        }

        /// <summary>Rejects offset-less timestamps so "local time" can never be assumed.</summary>
        private static bool HasExplicitUtcOffset(string value)
        {
            if (value.Length == 0)
            {
                return false;
            }
            var last = value[value.Length - 1];
            if (last == 'Z' || last == 'z')
            {
                return true;
            }
            if (value.Length < 6)
            {
                return false;
            }
            var sign = value[value.Length - 6];
            if (sign != '+' && sign != '-')
            {
                return false;
            }
            for (var i = value.Length - 5; i < value.Length; i++)
            {
                var c = value[i];
                if (i == value.Length - 3)
                {
                    if (c != ':')
                    {
                        return false;
                    }
                    continue;
                }
                if (c < '0' || c > '9')
                {
                    return false;
                }
            }
            return true;
        }
    }

    /// <summary>Accepts a JSON integer or a decimal string, parsed as <see cref="long"/>.</summary>
    internal sealed class LongFromNumberOrStringConverter : JsonConverter<long>
    {
        public override long Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            if (reader.TokenType == JsonTokenType.Number)
            {
                return reader.GetInt64();
            }
            if (reader.TokenType == JsonTokenType.String)
            {
                var text = reader.GetString();
                if (text != null
                    && long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed))
                {
                    return parsed;
                }
                throw new JsonException("value is not a decimal integer");
            }
            throw new JsonException("expected a JSON number or decimal string");
        }

        public override void Write(Utf8JsonWriter writer, long value, JsonSerializerOptions options)
        {
            writer.WriteNumberValue(value);
        }
    }

    internal static class BridgeJson
    {
        internal static readonly JsonSerializerOptions Read = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = false,
            AllowTrailingCommas = false,
            ReadCommentHandling = JsonCommentHandling.Disallow,
            NumberHandling = JsonNumberHandling.Strict,
        };

        internal static readonly JsonSerializerOptions Write = new JsonSerializerOptions
        {
            WriteIndented = false,
        };
    }
}
