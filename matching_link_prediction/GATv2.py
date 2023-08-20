#!/usr/bin/env python
# coding: utf-8

import dgl
import torch
import torch.nn.functional as F
import torch.nn as nn
from dgl.nn import GATv2Conv
from dgl.nn.pytorch import GATConv
from sklearn.metrics import roc_auc_score
import numpy as np
import torch.backends.cudnn as cudnn
import random
import pickle as pkl
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, accuracy_score
cudnn.benchmark = True
cudnn.enabled = True
torch.backends.cudnn.deterministic = True

"""
Graph Attention Networks in DGL using SPMV optimization.
References
----------
Paper: https://arxiv.org/pdf/2105.14491.pdf
Author's code: https://github.com/tech-srl/how_attentive_are_gats
"""

class GATv2(nn.Module):
    def __init__(
        self,
        num_layers,
        in_dim,
        num_hidden,
        num_classes,
        heads,
        activation,
        feat_drop,
        attn_drop,
        negative_slope,
        residual,
    ):
        super(GATv2, self).__init__()
        self.num_layers = num_layers
        self.gatv2_layers = nn.ModuleList()
        self.activation = activation
        # input projection (no residual)
        self.gatv2_layers.append(
            GATv2Conv(
                in_dim,
                num_hidden,
                heads[0],
                feat_drop,
                attn_drop,
                negative_slope,
                False,
                self.activation,
                bias=False,
                share_weights=True,
            )
        )
        # hidden layers
        for l in range(1, num_layers):
            # due to multi-head, the in_dim = num_hidden * num_heads
            self.gatv2_layers.append(
                GATv2Conv(
                    num_hidden * heads[l - 1],
                    num_hidden,
                    heads[l],
                    feat_drop,
                    attn_drop,
                    negative_slope,
                    residual,
                    self.activation,
                    bias=False,
                    share_weights=True,
                )
            )
        # output projection
        self.gatv2_layers.append(
            GATv2Conv(
                num_hidden * heads[-2],
                num_classes,
                heads[-1],
                feat_drop,
                attn_drop,
                negative_slope,
                residual,
                None,
                bias=False,
                share_weights=True,
            )
        )

    def forward(self, g, inputs):
        h = inputs
        for l in range(self.num_layers):
            h = self.gatv2_layers[l](g, h).flatten(1)
        # output projection
        logits = self.gatv2_layers[-1](g, h).mean(1)
        return logits


with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/G_dgl_training', 'rb') as f:
    G_dgl_training = pkl.load(f)

# print some features in G_dgl_training
print(G_dgl_training.ndata['features'][0:5])

# load /home/qian/HNE/Model/GCN/Ethereum/matching_link/positive_test_edge_indices.pkl, /home/qian/HNE/Model/GCN/Ethereum/matching_link/positive_train_edge_indices.pkl, /home/qian/HNE/Model/GCN/Ethereum/matching_link/positive_validation_edge_indices.pkl, /home/qian/HNE/Model/GCN/Ethereum/matching_link/negative_test_edge_indices.pkl, /home/qian/HNE/Model/GCN/Ethereum/matching_link/negative_train_edge_indices.pkl, /home/qian/HNE/Model/GCN/Ethereum/matching_link/negative_validation_edge_indices.pkl
with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/positive_test_edge_indices.pkl', 'rb') as f:
    positive_test_edge_indices = pkl.load(f)
    
with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/positive_train_edge_indices.pkl', 'rb') as f:
    positive_train_edge_indices = pkl.load(f)
    
with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/positive_validation_edge_indices.pkl', 'rb') as f:
    positive_validation_edge_indices = pkl.load(f)
    
with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/negative_test_edge_indices.pkl', 'rb') as f:
    negative_test_edge_indices = pkl.load(f)
    
with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/negative_train_edge_indices.pkl', 'rb') as f:
    negative_train_edge_indices = pkl.load(f)
    
with open('/home/qian/HNE/Model/GCN/Ethereum/matching_link/negative_validation_edge_indices.pkl', 'rb') as f:
    negative_validation_edge_indices = pkl.load(f)


# Get the number of input features
in_feats = 16 

# Define the model hyperparameters
num_layers = 3
in_dim = in_feats
num_hidden = 32
num_classes = 8
heads = [4, 4, 4]
activation = F.elu
feat_drop = 0
attn_drop = 0
negative_slope = 0.2
residual = False

# define generate_edge_embeddings function
def generate_edge_embeddings(h, edges):
    # Extract the source and target node indices from the edges
    src, dst = edges[0], edges[1]
    
    # Use the node indices to get the corresponding node embeddings
    src_embed = h[src]
    dst_embed = h[dst]

    # Concatenate the source and target node embeddings
    edge_embs = torch.cat([src_embed, dst_embed], dim=1)

    return edge_embs


def main():
    # write a loop to run 5 times of the model and get the average performance
    for i in range(5):
        model = GATv2(num_layers, in_dim, num_hidden, num_classes, heads, activation, feat_drop, attn_drop, negative_slope, True)
        # model = model.to('cuda:1')
        # train on positive edges, negative edges; also use validation edges to stop epochs
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        criterion = nn.BCEWithLogitsLoss()

        best_val_loss = float('inf')
        best_model = None
        num_epochs = 200
        patience = 20
        early_stopping_counter = 0
        
        
        transform = nn.Sequential(
        nn.Linear(16, 1))
        
        for epoch in range(num_epochs):
            model.train()
            
            # forward pass
            logits = model(G_dgl_training, G_dgl_training.ndata['features'].float())
            
            # generate edge embeddings
            pos_train_edge_embs = generate_edge_embeddings(logits, positive_train_edge_indices)
            neg_train_edge_embs = generate_edge_embeddings(logits, negative_train_edge_indices)
            
            # concatenete positive and negative edge embeddings
            train_edge_embs = torch.cat([pos_train_edge_embs, neg_train_edge_embs], dim=0)
            train_edge_labels = torch.cat([torch.ones(pos_train_edge_embs.shape[0]), torch.zeros(neg_train_edge_embs.shape[0])], dim=0).unsqueeze(1)
            
            # print shapes of tensors for debugging
            # print(f"Train Edge Embeddings Shape: {train_edge_embs.shape}")
            # print(f"Train Edge Labels Shape: {train_edge_labels.shape}")
            
            # calculate loss
            loss = criterion(transform(train_edge_embs), train_edge_labels)
            print(f"Training Loss: {loss.item()}")
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            
            # validation
            model.eval()
            
            with torch.no_grad():
                # repeat the same process as above for validation samples
                logits = model(G_dgl_training, G_dgl_training.ndata['features'].float())
                pos_val_edge_embs = generate_edge_embeddings(logits, positive_validation_edge_indices)
                neg_val_edge_embs = generate_edge_embeddings(logits, negative_validation_edge_indices)
                val_edge_embs = torch.cat([pos_val_edge_embs, neg_val_edge_embs], dim=0)
                val_edge_labels = torch.cat([torch.ones(pos_val_edge_embs.shape[0]), torch.zeros(neg_val_edge_embs.shape[0])], dim=0).unsqueeze(1)
                # # print shapes of tensors for debugging
                # print(f"Validation Edge Embeddings Shape: {val_edge_embs.shape}")
                # print(f"Validation Edge Labels Shape: {val_edge_labels.shape}")

                val_loss = criterion(transform(val_edge_embs), val_edge_labels)
                print(f"Validation Loss: {val_loss.item()}")
                
                # early stopping based on validation loss
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    # add patience
                    early_stopping_counter = 0
                    # # save the best model
                    best_model = copy.deepcopy(model)
                
                else:
                    early_stopping_counter += 1
                    if early_stopping_counter >= patience:
                        print("Early Stopping!")
                        break
                    
        # switch to evaluation mode
        best_model.eval()

        with torch.no_grad():
            # generate the embeddings using the best model
            logits = best_model(G_dgl_training, G_dgl_training.ndata['features'].float())

            # generate edge embeddings for the test samples
            pos_test_edge_embs = generate_edge_embeddings(logits, positive_test_edge_indices)
            neg_test_edge_embs = generate_edge_embeddings(logits, negative_test_edge_indices)

            # concatenate the positive and negative edge embeddings and labels
            test_edge_embs = torch.cat([pos_test_edge_embs, neg_test_edge_embs], dim=0)
            test_edge_labels = torch.cat([torch.ones(pos_test_edge_embs.shape[0]), torch.zeros(neg_test_edge_embs.shape[0])], dim=0)


            # test_loss = criterion(linear(test_edge_embs), val_edge_labels)
            # calculate predictions using the linear layer
            
            predictions = torch.sigmoid(transform(test_edge_embs))
            
            # reshape the predictions and the labels
            predictions = predictions.view(-1).cpu().numpy()
            test_edge_labels = test_edge_labels.cpu().numpy()
    
            auc = roc_auc_score(test_edge_labels, predictions)
            # here use 0.5 as threshold
            predictions_binary = (predictions > 0.5).astype(int)
            f1 = f1_score(test_edge_labels, predictions_binary)
            precision = precision_score(test_edge_labels, predictions_binary)
            recall = recall_score(test_edge_labels, predictions_binary)
            accuracy = accuracy_score(test_edge_labels, predictions_binary)
        # also record loss
        # print(f"Test Loss: {criterion(transform(test_edge_embs), test_edge_labels)}")
        print(f"AUC: {auc}")
        print(f"F1 Score: {f1}")
        print(f"Precision: {precision}")
        print(f"Recall: {recall}")
        print(f"Accuracy: {accuracy}")
        
        # write the result to a txt file
        with open('result.txt', 'a') as f:
            # write auc, f1, precision, recall
            f.write(f"AUC: {auc}, F1 Score: {f1}, Precision: {precision}, Recall: {recall}, Accuracy: {accuracy}\n")

if __name__ == '__main__':
    main()