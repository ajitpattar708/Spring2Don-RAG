
import json
import uuid
import sys
import os
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.settings import Settings
from src.rag.knowledge_base import KnowledgeBase
from src.rag.embeddings import EmbeddingModel

def add_gateway_pattern():
    settings = Settings()
    embedding_model = EmbeddingModel(settings)
    knowledge_base = KnowledgeBase(settings)
    
    # Define the pattern
    spring_code = """
import org.springframework.cloud.gateway.mvc.ProxyExchange;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class GatewayConfig {
    @GetMapping("/proxy/**")
    public ResponseEntity<?> proxy(ProxyExchange<byte[]> proxy) {
        return proxy.uri("http://example.com").get();
    }
}
"""

    helidon_code = """
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.core.Response;
import jakarta.inject.Inject;
import com.example.support.ProxyExchange;

@Path("/")
@ApplicationScoped
public class GatewayConfig {
    @Inject
    private ProxyExchange proxy;

    @GET
    @Path("/proxy/{path: .*}")
    public Response proxy() {
        return proxy.uri("http://example.com").get();
    }
}
// Note: Requires ProxyExchange shim class
"""

    pattern_id = str(uuid.uuid4())
    
    # 1. Update JSON Dataset
    dataset_file = Path(settings.chromadb_path).parent / 'migration_dataset.json'
    patterns = []
    if dataset_file.exists():
        with open(dataset_file, 'r', encoding='utf-8') as f:
            patterns = json.load(f)
            
    new_pattern = {
        "id": pattern_id,
        "migration_type": "code_pattern",
        "spring_pattern": spring_code.strip(),
        "helidon_pattern": helidon_code.strip(),
        "spring_version": "3.x",
        "helidon_version": "4.x",
        "description": "Spring Cloud Gateway MVC ProxyExchange pattern to Helidon JAX-RS with Shim",
        "source": "manual_addition",
        "created_at": datetime.now().isoformat()
    }
    
    patterns.append(new_pattern)
    
    with open(dataset_file, 'w', encoding='utf-8') as f:
        json.dump(patterns, f, indent=2)
        
    print(f"Added pattern to JSON: {dataset_file}")

    # 2. Update Vector DB
    print("Generating embedding...")
    embedding = embedding_model.encode_single(spring_code.strip())
    
    print("Adding to ChromaDB...")
    knowledge_base.add_patterns('code_patterns', [{
        'id': pattern_id,
        'text': f"Spring:\n{spring_code.strip()}\n\nHelidon:\n{helidon_code.strip()}",
        'embedding': embedding.tolist() if hasattr(embedding, 'tolist') else embedding,
        'metadata': {
            'migration_type': 'code_pattern',
            'spring_version': "3.x",
            'helidon_version': "4.x",
            'description': "Spring Cloud Gateway ProxyExchange"
        }
    }])
    
    print("Pattern successfully added to Knowledge Base.")

if __name__ == "__main__":
    add_gateway_pattern()
